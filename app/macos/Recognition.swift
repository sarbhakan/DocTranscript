import AVFoundation
import CryptoKit
import Foundation

enum NoteViveError: LocalizedError, Sendable {
    case model, modelIntegrity, stream, device, audio, conversion, decoding, backlog, capture, lexicon

    var errorDescription: String? {
        switch self {
        case .model: "Impossible de charger le moteur français local."
        case .modelIntegrity: "Le modèle local est incomplet ou altéré. Extrayez de nouveau tout le ZIP NoteVive."
        case .stream: "Impossible de démarrer une session de dictée."
        case .device: "Microphone indisponible. Vérifiez l’entrée audio dans Réglages Système."
        case .audio: "Impossible de lire le WAV de contrôle (PCM 16 bits mono attendu)."
        case .conversion: "Le format du microphone n’a pas pu être converti."
        case .decoding: "Le moteur n’a pas pu transcrire un passage."
        case .backlog: "Le moteur ne suit plus. Le dernier passage peut être incomplet."
        case .capture: "L’entrée audio a changé ou la capture ne suit plus."
        case .lexicon: "Le lexique local est indisponible ou incompatible."
        }
    }
}

private let recognitionRate: Int32 = 16_000

private func verifyModel(_ directory: URL) throws {
    let names = ["config.json", "vocab.txt", "encoder-model.int8.onnx",
                 "decoder_joint-model.int8.onnx", "nemo128.onnx", "silero_vad.onnx"]
    do {
        let manifest = try FileHandle(forReadingFrom: directory.appendingPathComponent("SHA256.json"))
        defer { try? manifest.close() }
        guard let data = try manifest.read(upToCount: 4097), data.count <= 4096 else {
            throw NoteViveError.modelIntegrity
        }
        let expected = try JSONDecoder().decode([String: String].self, from: data)
        guard Set(expected.keys) == Set(names) else { throw NoteViveError.modelIntegrity }
        for name in names {
            let url = directory.appendingPathComponent(name)
            let info = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
            guard info.isRegularFile == true, info.isSymbolicLink != true else {
                throw NoteViveError.modelIntegrity
            }
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            var hash = SHA256()
            while let bytes = try handle.read(upToCount: 1_048_576), !bytes.isEmpty {
                hash.update(data: bytes)
            }
            let actual = hash.finalize().map { String(format: "%02x", $0) }.joined()
            guard expected[name] == actual else { throw NoteViveError.modelIntegrity }
        }
    } catch {
        throw NoteViveError.modelIntegrity
    }
}

// Each object is accessed by one serial queue. Native samples and text are
// copied before their owning call returns.
private final class PhraseDecoder {
    private let handle: UnsafeMutableRawPointer

    init(directory: URL) throws {
        guard let created = directory.path.withCString({ NVUltiMedCreate($0) }) else {
            throw NoteViveError.model
        }
        handle = created
    }

    deinit { NVUltiMedDestroy(handle) }

    func configure(phrases: [String]) throws -> Int {
        let count = phrases.isEmpty ? NVUltiMedSetPhrases(handle, nil) :
            phrases.joined(separator: "\n").withCString { NVUltiMedSetPhrases(handle, $0) }
        guard count >= 0, phrases.isEmpty || count > 0 else { throw NoteViveError.lexicon }
        return Int(count)
    }

    func decode(_ samples: [Float]) throws -> String {
        var result: UnsafeMutablePointer<CChar>?
        let status = samples.withUnsafeBufferPointer {
            NVUltiMedDecode(handle, $0.baseAddress, Int32($0.count), &result)
        }
        defer { if let result { NVUltiMedFreeText(result) } }
        guard status == 0, let result, let text = String(validatingCString: result) else {
            throw NoteViveError.decoding
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private final class EmittedPhrases {
    var values: [[Float]] = []
}

private let receivePhrase: @convention(c) (UnsafeMutableRawPointer?, UnsafePointer<Float>?, Int) -> Int32 = {
    context, samples, count in
    guard let context, let samples, count > 0, count <= Int(recognitionRate) * 30 else { return -1 }
    let phrases = Unmanaged<EmittedPhrases>.fromOpaque(context).takeUnretainedValue()
    phrases.values.append(Array(UnsafeBufferPointer(start: samples, count: count)))
    return 0
}

private final class PauseDetector {
    private let handle: UnsafeMutableRawPointer

    init(directory: URL) throws {
        let file = directory.appendingPathComponent("silero_vad.onnx")
        guard let created = file.path.withCString({ nv_silero_create($0) }) else {
            throw NoteViveError.model
        }
        handle = created
    }

    deinit { nv_silero_destroy(handle) }

    func reset() { nv_silero_reset(handle) }

    func accept(_ pcm: [Float]) throws -> [[Float]] {
        guard !pcm.isEmpty else { return [] }
        let phrases = EmittedPhrases()
        let context = Unmanaged.passUnretained(phrases).toOpaque()
        let status = pcm.withUnsafeBufferPointer {
            nv_silero_accept(handle, $0.baseAddress, $0.count, receivePhrase, context)
        }
        guard status == 0 else { throw NoteViveError.decoding }
        return phrases.values
    }

    func finish() throws -> [[Float]] {
        let phrases = EmittedPhrases()
        let context = Unmanaged.passUnretained(phrases).toOpaque()
        guard nv_silero_finish(handle, receivePhrase, context) == 0 else { throw NoteViveError.decoding }
        return phrases.values
    }
}

private final class ConverterInput: @unchecked Sendable {
    // AVAudioConverter calls the block synchronously. The input buffer is
    // supplied once; reusing it for a second request duplicates audio.
    var next: AVAudioPCMBuffer?
    let end: Bool
    init(_ next: AVAudioPCMBuffer?, end: Bool = false) { self.next = next; self.end = end }
    func supply(_ status: UnsafeMutablePointer<AVAudioConverterInputStatus>) -> AVAudioBuffer? {
        if let buffer = next {
            next = nil
            status.pointee = .haveData
            return buffer
        }
        status.pointee = end ? .endOfStream : .noDataNow
        return nil
    }
}

private final class MonoConverter {
    private let input: AVAudioFormat
    private let target: AVAudioFormat
    private let converter: AVAudioConverter?
    let sourceRate: Int32

    init(sourceRate: Int32) throws {
        guard (8_000...192_000).contains(sourceRate),
              let input = AVAudioFormat(standardFormatWithSampleRate: Double(sourceRate), channels: 1),
              let target = AVAudioFormat(standardFormatWithSampleRate: Double(recognitionRate), channels: 1)
        else { throw NoteViveError.conversion }
        self.sourceRate = sourceRate
        self.input = input
        self.target = target
        if sourceRate == recognitionRate { converter = nil }
        else {
            guard let value = AVAudioConverter(from: input, to: target) else { throw NoteViveError.conversion }
            converter = value
        }
    }

    func convert(_ samples: [Float]) throws -> [Float] {
        guard let converter else { return samples }
        guard !samples.isEmpty else { return [] }
        guard let buffer = AVAudioPCMBuffer(pcmFormat: input, frameCapacity: AVAudioFrameCount(samples.count)),
              let channel = buffer.floatChannelData?.pointee else { throw NoteViveError.conversion }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { channel.update(from: $0.baseAddress!, count: $0.count) }
        let capacity = Int(ceil(Double(samples.count) * target.sampleRate / input.sampleRate)) + 256
        return try pull(converter, input: ConverterInput(buffer), capacity: capacity).0
    }

    func finish() throws -> [Float] {
        guard let converter else { return [] }
        let input = ConverterInput(nil, end: true)
        var tail: [Float] = []
        for _ in 0..<8 {
            let (samples, state) = try pull(converter, input: input, capacity: 512)
            tail.append(contentsOf: samples)
            if state == .endOfStream || state == .inputRanDry { return tail }
        }
        throw NoteViveError.conversion
    }

    private func pull(_ converter: AVAudioConverter, input: ConverterInput, capacity: Int)
        throws -> ([Float], AVAudioConverterOutputStatus) {
        guard let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: AVAudioFrameCount(capacity)),
              let channel = output.floatChannelData?.pointee else { throw NoteViveError.conversion }
        var failure: NSError?
        let status = converter.convert(to: output, error: &failure) { _, flag in input.supply(flag) }
        guard status != .error else { throw NoteViveError.conversion }
        return (Array(UnsafeBufferPointer(start: channel, count: Int(output.frameLength))), status)
    }
}

/// One persistent ASR instance; audio conversion and Silero never wait for
/// phrase decoding. Backpressure stops capture instead of dropping audio.
final class RecognitionWorker: @unchecked Sendable {
    typealias TextHandler = @Sendable (String) -> Void
    typealias ErrorHandler = @Sendable (NoteViveError) -> Void
    typealias MetricHandler = @Sendable (String, Double) -> Void
    let queue = DispatchQueue(label: "fr.notevive.capture", qos: .userInitiated)
    private let decodeQueue = DispatchQueue(label: "fr.notevive.transcription", qos: .userInitiated)
    private let model: URL
    private var detector: PauseDetector?
    private var converter: MonoConverter?
    private var active = false
    private var pending = 0
    // decodeQueue only
    private var decoder: PhraseDecoder?
    private var decodeFailed = false
    private var metric: MetricHandler?

    init(model: URL) { self.model = model }

    @discardableResult
    func start(phrases: [String] = [], metric: MetricHandler? = nil) throws -> Int {
        dispatchPrecondition(condition: .onQueue(queue))
        guard !active else { throw NoteViveError.stream }
        if detector == nil {
            try verifyModel(model)
            let newDetector = try PauseDetector(directory: model)
            try decodeQueue.sync { decoder = try PhraseDecoder(directory: model) }
            detector = newDetector
        }
        let accepted = try decodeQueue.sync {
            guard let decoder else { throw NoteViveError.model }
            let accepted = try decoder.configure(phrases: phrases)
            decodeFailed = false
            self.metric = metric
            return accepted
        }
        detector?.reset()
        converter = nil
        active = true
        return accepted
    }

    func accept(_ samples: [Float], rate: Int32, text: @escaping TextHandler, error: @escaping ErrorHandler) throws {
        dispatchPrecondition(condition: .onQueue(queue))
        guard active, let detector else { return }
        if converter == nil { converter = try MonoConverter(sourceRate: rate) }
        guard let converter, converter.sourceRate == rate else { throw NoteViveError.conversion }
        try submit(detector.accept(converter.convert(samples)), text: text, error: error)
    }

    private func submit(_ segments: [[Float]], text: @escaping TextHandler, error onError: @escaping ErrorHandler) throws {
        for segment in segments {
            guard pending < 4 else { throw NoteViveError.backlog }
            pending += 1
            decodeQueue.async { [self] in
                defer { queue.async { [self] in pending -= 1 } }
                guard !decodeFailed, let decoder else { return }
                do {
                    let start = metric == nil ? 0 : DispatchTime.now().uptimeNanoseconds
                    let phrase = try decoder.decode(segment)
                    if let metric { metric(phrase, Double(DispatchTime.now().uptimeNanoseconds - start) / 1e6) }
                    if !phrase.isEmpty { text(phrase) }
                } catch {
                    decodeFailed = true
                    onError(.decoding)
                }
            }
        }
    }

    func stop(flush: Bool, text: @escaping TextHandler, error reportError: @escaping ErrorHandler,
              done: @escaping @Sendable () -> Void) {
        dispatchPrecondition(condition: .onQueue(queue))
        if active, let detector, flush {
            do {
                if let converter {
                    try submit(detector.accept(converter.finish()), text: text, error: reportError)
                }
                try submit(detector.finish(), text: text, error: reportError)
            } catch let issue as NoteViveError { reportError(issue) }
            catch { reportError(.decoding) }
        }
        active = false
        converter = nil
        detector?.reset()
        decodeQueue.async(execute: done)
    }

    // Accelerated fixture replay has no natural time between audio packets.
    // Let decoding catch up between them without affecting microphone capture.
    fileprivate func drainForReplay() {
        dispatchPrecondition(condition: .onQueue(queue))
        decodeQueue.sync {}
    }
}

// Admission is bounded. The audio callback never waits for either model.
final class AudioIngress: @unchecked Sendable {
    private let worker: RecognitionWorker
    private let text: RecognitionWorker.TextHandler
    private let interrupted: RecognitionWorker.ErrorHandler
    private let lock = NSLock()
    private var accepting = true
    private var pending = 0

    init(worker: RecognitionWorker, text: @escaping RecognitionWorker.TextHandler,
         interrupted: @escaping RecognitionWorker.ErrorHandler) {
        self.worker = worker
        self.text = text
        self.interrupted = interrupted
    }

    // The Core Audio callback must not inherit the main actor in Swift 6.
    nonisolated func installTap(on node: AVAudioNode, rate: Int32,
                               observer: (@Sendable (AVAudioPCMBuffer, AVAudioTime) -> Void)? = nil) {
        let callback: @Sendable (AVAudioPCMBuffer, AVAudioTime) -> Void = { [self] buffer, time in
            if push(buffer, rate: rate) { observer?(buffer, time) }
        }
        node.installTap(onBus: 0, bufferSize: 2_048, format: nil, block: callback)
    }

    private func push(_ buffer: AVAudioPCMBuffer, rate: Int32) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard accepting, buffer.frameLength > 0 else { return false }
        guard pending < 24, buffer.frameLength <= 16_384,
              abs(buffer.format.sampleRate - Double(rate)) < 0.5,
              let first = buffer.floatChannelData?.pointee else {
            accepting = false
            worker.queue.async { [self] in interrupted(.capture) }
            return false
        }
        let count = Int(buffer.frameLength)
        let stride = buffer.stride
        let packet = stride == 1
            ? Array(UnsafeBufferPointer(start: first, count: count))
            : (0..<count).map { first[$0 * stride] }
        pending += 1
        worker.queue.async { [self] in
            lock.lock()
            let canAccept = !failed
            lock.unlock()
            if canAccept {
                do { try worker.accept(packet, rate: rate, text: text, error: fail) }
                catch let issue as NoteViveError { fail(issue) }
                catch { fail(.decoding) }
            }
            lock.lock()
            pending -= 1
            lock.unlock()
        }
        return true
    }

    private var failed = false

    private func fail(_ issue: NoteViveError) {
        lock.lock()
        let first = !failed
        failed = true
        accepting = false
        lock.unlock()
        if first { interrupted(issue) }
    }

    func close() {
        lock.lock()
        accepting = false
        lock.unlock()
    }
}

struct ReplaySegment: Encodable, Sendable {
    let audio_ms: Int?
    let decode_ms: Double
    let text: String
}

struct DictationReplay: Encodable, Sendable {
    let profile: String
    let accepted_terms: Int
    let setup_ms: Double
    let selection_ms: Double
    let pause: [ReplaySegment]
    let stop: [ReplaySegment]
    let elapsed_ms: Double
}

private final class ReplayEvidence: @unchecked Sendable {
    private let lock = NSLock()
    private var phrases: [(String, Double)] = []
    private var issue: NoteViveError?

    func append(_ phrase: String, _ milliseconds: Double) {
        lock.withLock { phrases.append((phrase, milliseconds)) }
    }
    func failed(_ error: NoteViveError) { lock.withLock { issue = error } }
    func take(at audioMS: Int?) throws -> [ReplaySegment] {
        try lock.withLock {
            if let issue { throw issue }
            let result = phrases.map { ReplaySegment(audio_ms: audioMS, decode_ms: $0.1, text: $0.0) }
            phrases.removeAll(keepingCapacity: true)
            return result
        }
    }
}

func replayDictation(worker: RecognitionWorker, samples: [Float], rate: Int32,
                     profile: String = "", phrases: [String] = [], selectionMS: Double = 0) throws -> DictationReplay {
    let evidence = ReplayEvidence()
    let setup = DispatchTime.now().uptimeNanoseconds
    let accepted = try worker.queue.sync { try worker.start(phrases: phrases, metric: evidence.append) }
    let started = DispatchTime.now().uptimeNanoseconds
    let step = Int(rate) / 10
    var paused: [ReplaySegment] = []
    var finished = false
    defer {
        if !finished {
            worker.queue.sync {
                worker.stop(flush: false, text: { _ in }, error: evidence.failed, done: {})
                worker.drainForReplay()
            }
        }
    }
    for offset in stride(from: 0, to: samples.count, by: step) {
        let end = min(samples.count, offset + step)
        let packet = Array(samples[offset..<end])
        try worker.queue.sync {
            try worker.accept(packet, rate: rate, text: { _ in }, error: evidence.failed)
            worker.drainForReplay()
        }
        paused += try evidence.take(at: end * 1_000 / Int(rate))
    }
    worker.queue.sync {
        worker.stop(flush: true, text: { _ in }, error: evidence.failed, done: {})
        worker.drainForReplay()
    }
    finished = true
    let stopped = try evidence.take(at: nil)
    return DictationReplay(profile: profile, accepted_terms: accepted, setup_ms: Double(started - setup) / 1e6,
                           selection_ms: selectionMS,
                           pause: paused, stop: stopped,
                           elapsed_ms: Double(DispatchTime.now().uptimeNanoseconds - started) / 1e6)
}
