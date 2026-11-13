import AppKit
import AVFoundation
import SwiftUI
import UniformTypeIdentifiers

@MainActor final class Dictation: ObservableObject {
    enum Phase { case idle, authorizing, loading, listening, stopping }

    @Published var note = "" {
        didSet { if note != oldValue { onNoteChange?(note) } }
    }
    var onNoteChange: (@MainActor (String) -> Void)?
    @Published private(set) var draft = ""
    @Published private(set) var phase = Phase.idle
    @Published private(set) var status = "Micro coupé"
    @Published private(set) var isExporting = false

    private let worker: RecognitionWorker
    private var engine: AVAudioEngine?
    private var inputNode: AVAudioInputNode?
    private var ingress: AudioIngress?
    private var engineObservation: NSObjectProtocol?
    private var generation = 0
    private var keepPending = false
    private var exported = ""

    var needsExport: Bool { !note.isEmpty && note != exported }
    var canSwitchNote: Bool { phase == .idle && !isExporting }

    init(model: URL) { worker = RecognitionWorker(model: model) }

    func toggle() {
        if phase == .idle { begin() }
        else if phase == .listening || phase == .loading { end(flush: true) }
    }

    private func begin() {
        generation += 1
        let run = generation
        keepPending = false
        draft = ""
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            prepare(run)
        case .notDetermined:
            phase = .authorizing
            status = "Autorisation du micro attendue"
            AVCaptureDevice.requestAccess(for: .audio) { @Sendable [weak self] authorized in
                DispatchQueue.main.async {
                    guard let self, self.generation == run, self.phase == .authorizing else { return }
                    if authorized && NSApp.isActive { self.prepare(run) }
                    else if authorized {
                        self.phase = .idle
                        self.status = "Micro autorisé · Cliquez sur Dicter pour commencer"
                    } else { self.denied() }
                }
            }
        default:
            denied()
        }
    }

    private func denied() {
        phase = .idle
        status = "Micro non autorisé · Réglages Système → Confidentialité et sécurité → Microphone"
    }

    private func prepare(_ run: Int) {
        phase = .loading
        status = "Micro coupé · Préparation du moteur local…"
        worker.queue.async { [worker, weak self] in
            do {
                try worker.start()
                DispatchQueue.main.async {
                    guard let self, self.generation == run, self.phase == .loading else { return }
                    do { try self.openMicrophone(run) }
                    catch { self.end(flush: false, message: "Micro coupé · \(error.localizedDescription)") }
                }
            } catch {
                DispatchQueue.main.async {
                    guard let self, self.generation == run, self.phase == .loading else { return }
                    self.phase = .idle
                    self.status = "Micro coupé · \(error.localizedDescription)"
                }
            }
        }
    }

    private func openMicrophone(_ run: Int) throws {
        let audio = AVAudioEngine()
        let input = audio.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.channelCount > 0, format.commonFormat == .pcmFormatFloat32,
              format.sampleRate.isFinite, format.sampleRate >= 8_000, format.sampleRate <= 192_000 else {
            throw NoteViveError.device
        }
        let rate = Int32(format.sampleRate.rounded())
        let receiver = AudioIngress(worker: worker, update: { [weak self] update in
            guard let self, self.generation == run,
                  self.phase == .listening || (self.phase == .stopping && self.keepPending) else { return }
            self.append(update.committed)
            self.draft = update.draft
        }, interrupted: { [weak self] in
            guard let self, self.generation == run else { return }
            self.interrupt("Dictée interrompue : l’entrée audio a changé ou le moteur ne suit plus")
        })
        receiver.installTap(on: input, rate: rate)
        engine = audio
        inputNode = input
        ingress = receiver
        engineObservation = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: audio, queue: nil
        ) { @Sendable [weak self] _ in
            DispatchQueue.main.async {
                guard let self, self.generation == run else { return }
                self.interrupt("Dictée interrompue : le périphérique audio a changé")
            }
        }
        audio.prepare()
        try audio.start()
        phase = .listening
        status = "Micro ouvert · Dictée en cours"
    }

    func interrupt(_ reason: String) {
        if phase == .loading || phase == .listening {
            end(flush: false, message: "Micro coupé · \(reason)")
        }
    }

    private func end(flush: Bool, message: String = "Micro coupé · Relisez le texte") {
        let run = generation
        keepPending = flush && phase == .listening
        let retain = keepPending
        phase = .stopping
        status = "Micro coupé · Fin de la dictée…"
        ingress?.close()
        ingress = nil
        if let engineObservation { NotificationCenter.default.removeObserver(engineObservation) }
        engineObservation = nil
        inputNode?.removeTap(onBus: 0)
        inputNode = nil
        engine?.stop()
        engine = nil
        if !retain { draft = "" }
        worker.queue.async { [worker, weak self] in
            let last = worker.stop(flush: retain)
            DispatchQueue.main.async {
                guard let self, self.generation == run else { return }
                if retain { self.append(last) }
                self.draft = ""
                self.phase = .idle
                self.status = message
            }
        }
    }

    private func append(_ text: String) {
        guard !text.isEmpty else { return }
        let separator = note.last.map { $0.isWhitespace ? "" : " " } ?? ""
        note += separator + text
    }

    func exportNote(title: String? = nil) {
        guard phase == .idle, !note.isEmpty, !isExporting else { return }
        let panel = NSSavePanel()
        panel.title = "Exporter le brouillon"
        panel.allowedContentTypes = [.plainText]
        let invalid = CharacterSet.controlCharacters.union(CharacterSet(charactersIn: "/:"))
        let safe = (title ?? "").components(separatedBy: invalid).joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines.union(CharacterSet(charactersIn: ".")))
        panel.nameFieldStringValue = (safe.isEmpty ? "NoteVive-brouillon" : String(safe.prefix(90))) + ".txt"
        panel.isExtensionHidden = false
        panel.message = "Le fichier texte exporté n’est pas chiffré."
        isExporting = true
        let snapshot = note
        panel.begin { [weak self] response in
            guard let self else { return }
            self.isExporting = false
            guard response == .OK, let url = panel.url else { return }
            do {
                try snapshot.write(to: url, atomically: true, encoding: .utf8)
                self.exported = snapshot
                self.status = "Micro coupé · Texte exporté"
            } catch {
                self.status = "Micro coupé · Échec de l’export. Choisissez un dossier accessible."
            }
        }
    }
}
