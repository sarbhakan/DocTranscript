import AppKit
import SwiftUI

@MainActor final class Application: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let dictation: Dictation
    private var window: NSWindow?
    private var sleepObserver: NSObjectProtocol?
    private var closingWindow = false

    init(model: URL) { dictation = Dictation(model: model) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let name = "NoteVive"
        let menu = NSMenu()
        let applicationItem = NSMenuItem()
        let applicationMenu = NSMenu(title: name)
        applicationMenu.addItem(withTitle: "À propos de NoteVive",
                                action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(withTitle: "Masquer NoteVive",
                                action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(withTitle: "Quitter NoteVive",
                                action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(applicationItem)
        applicationItem.submenu = applicationMenu
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Édition")
        for (title, selector, key) in [
            ("Annuler", "undo:", "z"), ("Couper", "cut:", "x"), ("Copier", "copy:", "c"),
            ("Coller", "paste:", "v"), ("Tout sélectionner", "selectAll:", "a")
        ] {
            edit.addItem(withTitle: title, action: NSSelectorFromString(selector), keyEquivalent: key)
        }
        menu.addItem(editItem)
        editItem.submenu = edit
        NSApp.mainMenu = menu

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 535),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "NoteVive · Dictée locale"
        window.contentViewController = NSHostingController(rootView: DictationView(dictation: dictation))
        window.contentMinSize = NSSize(width: 660, height: 460)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window
        NSApp.activate()

        sleepObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.willSleepNotification, object: nil, queue: .main
        ) { [weak self] _ in
            DispatchQueue.main.async { self?.dictation.interrupt("Dictée interrompue par la mise en veille") }
        }
    }

    func applicationDidResignActive(_ notification: Notification) {
        dictation.interrupt("Dictée interrompue : NoteVive est passé à l’arrière-plan")
    }

    func windowWillMiniaturize(_ notification: Notification) {
        dictation.interrupt("Dictée interrompue : la fenêtre a été réduite")
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        dictation.interrupt("Dictée arrêtée")
        closingWindow = confirmDiscard()
        return closingWindow
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        dictation.interrupt("Dictée arrêtée")
        return closingWindow || confirmDiscard() ? .terminateNow : .terminateCancel
    }

    private func confirmDiscard() -> Bool {
        guard dictation.needsExport else { return true }
        let alert = NSAlert()
        alert.messageText = "Fermer ce brouillon sans l’exporter ?"
        alert.informativeText = "Le brouillon est uniquement en mémoire. Cliquez sur Revenir pour l’exporter en fichier texte."
        alert.addButton(withTitle: "Revenir")
        alert.addButton(withTitle: "Fermer sans exporter")
        return alert.runModal() == .alertSecondButtonReturn
    }
}

private func selfTest(model: URL) throws {
    let recognizer = try Recognizer(model: model)
    try recognizer.start()
    // The caller opens the file and passes bytes on stdin; the sandbox stays in force.
    let limit = 20 * 1024 * 1024
    guard let data = try FileHandle.standardInput.read(upToCount: limit + 1),
          data.count <= limit,
          let wave = data.withUnsafeBytes({ bytes in
              SherpaOnnxReadWaveFromBinaryData(bytes.bindMemory(to: CChar.self).baseAddress, Int32(bytes.count))
          }) else { throw NoteViveError.audio }
    defer { SherpaOnnxFreeWave(wave) }
    guard let samples = wave.pointee.samples, wave.pointee.sample_rate > 0 else { throw NoteViveError.audio }
    let step = Int(wave.pointee.sample_rate / 10)
    guard step > 0 else { throw NoteViveError.audio }
    let count = Int(wave.pointee.num_samples)
    var committed: [String] = []
    var updates = 0
    for first in stride(from: 0, to: count, by: step) {
        let slice = UnsafeBufferPointer(start: samples + first, count: min(step, count - first))
        if let update = recognizer.accept(slice, rate: wave.pointee.sample_rate) {
            if !update.committed.isEmpty { committed.append(update.committed) }
            if !update.draft.isEmpty { updates += 1 }
        }
    }
    let last = recognizer.stop(flush: true)
    if !last.isEmpty { committed.append(last) }
    print("hypotheses=\(updates)")
    print("texte=\(committed.joined(separator: " "))")
}

let model = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/Model", isDirectory: true)
if CommandLine.arguments.dropFirst().elementsEqual(["--self-test"]) {
    do { try selfTest(model: model) }
    catch {
        FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8))
        exit(1)
    }
} else {
    MainActor.assumeIsolated {
        let app = NSApplication.shared
        let delegate = Application(model: model)
        app.setActivationPolicy(.regular)
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
