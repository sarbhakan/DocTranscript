import AVFoundation
import Foundation

struct RecognitionUpdate: Sendable {
    var committed = ""
    var draft = ""
}

enum NoteViveError: LocalizedError {
    case model, stream, device, audio

    var errorDescription: String? {
        switch self {
        case .model: "Impossible de charger le moteur français local."
        case .stream: "Impossible de démarrer une session de dictée."
        case .device: "Microphone indisponible. Vérifiez l’entrée audio dans Réglages Système."
        case .audio: "Impossible de lire le WAV de contrôle (PCM mono attendu)."
        }
    }
}

// The recognizer and the stream are used only on one serial queue.
final class Recognizer {
    private let handle: OpaquePointer
    private var stream: OpaquePointer?
    private var rate: Int32 = 0
    private var previousDraft = ""

    init(model: URL) throws {
        let names = ["encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"]
        let paths = names.map { model.appendingPathComponent($0).path }
        guard paths.allSatisfy({ FileManager.default.isReadableFile(atPath: $0) }),
              String(cString: SherpaOnnxGetVersionStr()) == "2.0.1" else {
            throw NoteViveError.model
        }
        let value = paths[0].withCString { encoder in
            paths[1].withCString { decoder in
                paths[2].withCString { joiner in
                    paths[3].withCString { tokens in
                        "cpu".withCString { provider in
                            "greedy_search".withCString { method in
                                var cfg = SherpaOnnxOnlineRecognizerConfig()
                                cfg.feat_config.sample_rate = 16_000
                                cfg.feat_config.feature_dim = 80
                                cfg.model_config.transducer.encoder = encoder
                                cfg.model_config.transducer.decoder = decoder
                                cfg.model_config.transducer.joiner = joiner
                                cfg.model_config.tokens = tokens
                                cfg.model_config.provider = provider
                                cfg.model_config.num_threads = 2
                                cfg.decoding_method = method
                                cfg.enable_endpoint = 1
                                cfg.rule1_min_trailing_silence = 2.4
                                cfg.rule2_min_trailing_silence = 1.2
                                cfg.rule3_min_utterance_length = 20
                                return SherpaOnnxCreateOnlineRecognizer(&cfg)
                            }
                        }
                    }
                }
            }
        }
        guard let value else { throw NoteViveError.model }
        handle = value
    }

    deinit {
        if let stream { SherpaOnnxDestroyOnlineStream(stream) }
        SherpaOnnxDestroyOnlineRecognizer(handle)
    }

    func start() throws {
        precondition(stream == nil)
        guard let created = SherpaOnnxCreateOnlineStream(handle) else {
            throw NoteViveError.stream
        }
        stream = created
        previousDraft = ""
        rate = 0
    }

    private func text(_ stream: OpaquePointer) -> String {
        guard let result = SherpaOnnxGetOnlineStreamResult(handle, stream) else { return "" }
        defer { SherpaOnnxDestroyOnlineRecognizerResult(result) }
        guard let value = result.pointee.text else { return "" }
        return String(cString: value).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func decode(_ stream: OpaquePointer) {
        while SherpaOnnxIsOnlineStreamReady(handle, stream) != 0 {
            SherpaOnnxDecodeOnlineStream(handle, stream)
        }
    }

    func accept(_ samples: UnsafeBufferPointer<Float>, rate: Int32) -> RecognitionUpdate? {
        guard let stream, let first = samples.baseAddress, !samples.isEmpty,
              rate > 0, self.rate == 0 || self.rate == rate else { return nil }
        self.rate = rate
        SherpaOnnxOnlineStreamAcceptWaveform(stream, rate, first, Int32(samples.count))
        decode(stream)
        let current = text(stream)
        if SherpaOnnxOnlineStreamIsEndpoint(handle, stream) != 0 {
            SherpaOnnxOnlineStreamReset(handle, stream)
            let changed = !previousDraft.isEmpty || !current.isEmpty
            previousDraft = ""
            return changed ? RecognitionUpdate(committed: current) : nil
        }
        guard previousDraft != current else { return nil }
        previousDraft = current
        return RecognitionUpdate(draft: current)
    }

    func stop(flush: Bool) -> String {
        guard let stream else { return "" }
        defer {
            SherpaOnnxDestroyOnlineStream(stream)
            self.stream = nil
        }
        guard flush, rate > 0 else { return "" }
        // Pad the last frame so Zipformer's right context can finish decoding it.
        let padding = [Float](repeating: 0, count: Int(rate))
        padding.withUnsafeBufferPointer {
            SherpaOnnxOnlineStreamAcceptWaveform(stream, rate, $0.baseAddress, Int32($0.count))
        }
        SherpaOnnxOnlineStreamInputFinished(stream)
        decode(stream)
        return text(stream)
    }
}

final class RecognitionWorker: @unchecked Sendable {
    let queue = DispatchQueue(label: "fr.notevive.reconnaissance", qos: .userInitiated)
    private let model: URL
    private var recognizer: Recognizer?

    init(model: URL) { self.model = model }

    func start() throws {
        dispatchPrecondition(condition: .onQueue(queue))
        if recognizer == nil { recognizer = try Recognizer(model: model) }
        try recognizer?.start()
    }

    func accept(_ samples: [Float], rate: Int32) -> RecognitionUpdate? {
        dispatchPrecondition(condition: .onQueue(queue))
        return samples.withUnsafeBufferPointer { recognizer?.accept($0, rate: rate) }
    }

    func stop(flush: Bool) -> String {
        dispatchPrecondition(condition: .onQueue(queue))
        return recognizer?.stop(flush: flush) ?? ""
    }
}

// Admission is bounded: a slow decoder stops the microphone instead of queuing
// unbounded audio or silently losing part of a dictation. Never wait for decoding
// on the audio callback. Once closed, no packet can be enqueued after stop().
final class AudioIngress: @unchecked Sendable {
    private let worker: RecognitionWorker
    private let update: @MainActor @Sendable (RecognitionUpdate) -> Void
    private let interrupted: @MainActor @Sendable () -> Void
    private let lock = NSLock()
    private var accepting = true
    private var pending = 0

    init(worker: RecognitionWorker, update: @escaping @MainActor @Sendable (RecognitionUpdate) -> Void,
         interrupted: @escaping @MainActor @Sendable () -> Void) {
        self.worker = worker
        self.update = update
        self.interrupted = interrupted
    }

    func push(_ buffer: AVAudioPCMBuffer, rate: Int32) {
        lock.lock()
        defer { lock.unlock() }
        guard accepting, buffer.frameLength > 0 else { return }
        guard pending < 12, buffer.frameLength <= 16_384, let first = buffer.floatChannelData?.pointee else {
            accepting = false
            DispatchQueue.main.async { self.interrupted() }
            return
        }
        let count = Int(buffer.frameLength)
        let stride = buffer.stride
        let packet = stride == 1
            ? Array(UnsafeBufferPointer(start: first, count: count))
            : (0..<count).map { first[$0 * stride] }
        pending += 1
        worker.queue.async { [self] in
            let next = worker.accept(packet, rate: rate)
            lock.lock()
            pending -= 1
            lock.unlock()
            if let next { DispatchQueue.main.async { self.update(next) } }
        }
    }

    func close() {
        lock.lock()
        accepting = false
        lock.unlock()
    }
}
