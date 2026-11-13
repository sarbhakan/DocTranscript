import AVFoundation
import Foundation

private enum AudioRegressionError: LocalizedError {
    case preparation, render, callback

    var errorDescription: String? {
        switch self {
        case .preparation: "Impossible de préparer le signal audio de contrôle."
        case .render: "Le moteur audio n’a pas pu rendre le signal de contrôle."
        case .callback: "Le signal de contrôle n’a pas atteint le rappel audio en arrière-plan."
        }
    }
}

private final class TapEvidence: @unchecked Sendable {
    private let condition = NSCondition()
    private var callbacks = 0
    private var frames = 0
    private var hasSignal = false

    func record(_ buffer: AVAudioPCMBuffer) {
        let signal = buffer.floatChannelData.map { channels in
            (0..<Int(buffer.frameLength)).contains { abs(channels[0][$0 * buffer.stride]) > 0.01 }
        } ?? false
        condition.lock()
        if !Thread.isMainThread { callbacks += 1 }
        frames += Int(buffer.frameLength)
        hasSignal = hasSignal || signal
        condition.broadcast()
        condition.unlock()
    }

    func result() throws -> (callbacks: Int, frames: Int) {
        let deadline = Date().addingTimeInterval(3)
        condition.lock()
        defer { condition.unlock() }
        while callbacks < 2 || frames < 4_096 || !hasSignal {
            guard condition.wait(until: deadline) else { throw AudioRegressionError.callback }
        }
        return (callbacks, frames)
    }
}

/// Uses Core Audio's real tap callback queue without opening the microphone or speakers.
/// Unlike the WAV smoke test, this catches accidental main actor isolation of the tap.
func audioCallbackRegression(model: URL) throws {
    let worker = RecognitionWorker(model: model)
    for run in 1...3 {
        let result = try renderWithTap(worker: worker)
        print("tap Core Audio sans micro [\(run)] : \(result.callbacks) rappels hors thread principal, \(result.frames) échantillons")
    }
}

private func renderWithTap(worker: RecognitionWorker) throws -> (callbacks: Int, frames: Int) {
    try worker.queue.sync { try worker.start() }
    let ingress = AudioIngress(worker: worker, update: { _ in }, interrupted: {})
    defer {
        ingress.close()
        _ = worker.queue.sync { worker.stop(flush: false) }
    }

    let sampleRate: Int32 = 16_000
    let frameCount: AVAudioFrameCount = 16_000
    let step: AVAudioFrameCount = 1_024
    guard let format = AVAudioFormat(standardFormatWithSampleRate: Double(sampleRate), channels: 1),
          let source = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount),
          let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: step),
          let samples = source.floatChannelData?.pointee else { throw AudioRegressionError.preparation }
    source.frameLength = frameCount
    for i in 0..<Int(frameCount) {
        samples[i] = Float(sin(Double(i) * 2 * .pi * 440 / Double(sampleRate)) * 0.25)
    }

    let engine = AVAudioEngine()
    let player = AVAudioPlayerNode()
    engine.attach(player)
    let mixer = engine.mainMixerNode
    engine.connect(player, to: mixer, format: format)
    try engine.enableManualRenderingMode(.offline, format: format, maximumFrameCount: step)
    let evidence = TapEvidence()
    ingress.installTap(on: mixer, rate: sampleRate) { buffer, _ in
        evidence.record(buffer)
    }
    defer {
        player.stop()
        mixer.removeTap(onBus: 0)
        engine.stop()
    }
    try engine.start()
    player.scheduleBuffer(source, at: nil)
    player.play()
    for _ in 0..<Int(frameCount / step) {
        guard try engine.renderOffline(step, to: output) == .success else { throw AudioRegressionError.render }
    }
    return try evidence.result()
}
