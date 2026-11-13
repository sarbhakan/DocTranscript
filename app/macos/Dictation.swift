import AppKit
import AVFoundation
import SwiftUI
import UniformTypeIdentifiers

@MainActor final class Dictation: ObservableObject {
    enum Phase { case idle, authorizing, loading, listening, stopping }

    @Published var note = ""
    @Published private(set) var draft = ""
    @Published private(set) var phase = Phase.idle
    @Published private(set) var status = "Micro coupé"
    @Published private(set) var isExporting = false

    private let worker: RecognitionWorker
    private var engine: AVAudioEngine?
    private var ingress: AudioIngress?
    private var engineObservation: NSObjectProtocol?
    private var generation = 0
    private var keepPending = false
    private var exported = ""

    var needsExport: Bool { !note.isEmpty && note != exported }

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
            AVCaptureDevice.requestAccess(for: .audio) { [weak self] authorized in
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
            self.interrupt("Dictée interrompue : l’entrée audio n’a pas pu être traitée assez vite")
        })
        input.installTap(onBus: 0, bufferSize: 2_048, format: nil) { buffer, _ in
            receiver.push(buffer, rate: rate)
        }
        engine = audio
        ingress = receiver
        audio.prepare()
        try audio.start()
        engineObservation = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: audio, queue: .main
        ) { [weak self] _ in
            DispatchQueue.main.async {
                guard let self, self.generation == run else { return }
                self.interrupt("Dictée interrompue : le périphérique audio a changé")
            }
        }
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
        if let engine {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
        }
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
        if let last = note.last, !last.isWhitespace { note += " " }
        note += text
    }

    func exportNote() {
        guard phase == .idle, !note.isEmpty, !isExporting else { return }
        let panel = NSSavePanel()
        panel.title = "Exporter le brouillon"
        panel.allowedContentTypes = [.plainText]
        panel.nameFieldStringValue = "NoteVive-brouillon.txt"
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

struct DictationView: View {
    @ObservedObject var dictation: Dictation

    private var recording: Bool { dictation.phase == .listening }
    private var preparing: Bool { dictation.phase == .loading }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 13) {
                if let url = Bundle.main.url(forResource: "Logo", withExtension: "png"),
                   let logo = NSImage(contentsOf: url) {
                    Image(nsImage: logo)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 46, height: 46)
                        .accessibilityHidden(true)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text("NoteVive").font(.system(size: 26, weight: .semibold))
                    Text("Dictée française hors ligne · Essai sur données fictives")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button {
                    dictation.toggle()
                } label: {
                    Label(recording ? "Arrêter" : preparing ? "Annuler" : "Dicter",
                          systemImage: recording ? "stop.fill" : preparing ? "xmark" : "mic")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .keyboardShortcut("d", modifiers: [.command])
                .disabled(dictation.phase == .authorizing || dictation.phase == .stopping || dictation.isExporting)
            }

            Label(dictation.status, systemImage: recording ? "mic.fill" : "mic.slash")
                .font(.system(.subheadline, weight: .medium))
                .foregroundStyle(recording ? Color.red : Color.secondary)
                .accessibilityIdentifier("etat-micro")

            VStack(alignment: .leading, spacing: 6) {
                Text("Texte provisoire").font(.headline)
                ScrollView {
                    Text(dictation.draft.isEmpty ? "Le texte apparaît ici pendant la dictée." : dictation.draft)
                        .foregroundStyle(dictation.draft.isEmpty ? .secondary : .primary)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(height: 46)
                .padding(10)
                .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 8))
                .accessibilityIdentifier("texte-provisoire")
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("Brouillon à relire").font(.headline)
                TextEditor(text: $dictation.note)
                    .font(.system(size: 15))
                    .padding(5)
                    .frame(minHeight: 110)
                    .overlay { RoundedRectangle(cornerRadius: 8).strokeBorder(.quaternary) }
                    .accessibilityLabel("Brouillon à relire")
                    .accessibilityIdentifier("brouillon")
            }
            HStack {
                Text("L’audio n’est pas enregistré. Le brouillon reste en mémoire jusqu’à l’export.")
                    .font(.footnote).foregroundStyle(.secondary)
                Spacer()
                Button("Exporter le texte…") { dictation.exportNote() }
                    .keyboardShortcut("s", modifiers: [.command, .shift])
                    .disabled(dictation.note.isEmpty || dictation.phase != .idle || dictation.isExporting)
            }
        }
        .padding(24)
        .frame(minWidth: 660, minHeight: 460)
    }
}
