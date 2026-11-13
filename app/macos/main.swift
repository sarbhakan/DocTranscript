import AppKit
import SwiftUI

@MainActor final class Application: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let dictation: Dictation
    let workspace: TranscriptWorkspace
    private var window: NSWindow?
    private var sleepObserver: NSObjectProtocol?

    init(model: URL) {
        let dictation = Dictation(model: model)
        self.dictation = dictation
        self.workspace = TranscriptWorkspace(library: TranscriptLibrary(), dictation: dictation)
    }

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

        showMainWindow()

        sleepObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.willSleepNotification, object: nil, queue: nil
        ) { @Sendable [weak self] _ in
            DispatchQueue.main.async { self?.dictation.interrupt("Dictée interrompue par la mise en veille") }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return false
    }

    private func makeMainWindow() -> NSWindow {
        let visibleFrame = NSScreen.main?.visibleFrame
        let width = min(995, (visibleFrame?.width ?? 1_035) - 40)
        let height = min(615, (visibleFrame?.height ?? 655) - 40)
        let newWindow = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: width, height: height),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        newWindow.title = "NoteVive · Dictée locale"
        newWindow.contentViewController = NSHostingController(rootView: LibraryView(workspace: workspace))
        newWindow.contentMinSize = NSSize(width: min(740, width), height: min(500, height))
        newWindow.collectionBehavior.insert(.moveToActiveSpace)
        newWindow.isRestorable = false
        newWindow.isReleasedWhenClosed = false
        newWindow.delegate = self
        newWindow.center()
        return newWindow
    }

    private func showMainWindow() {
        let window = self.window ?? makeMainWindow()
        self.window = window
        if window.isMiniaturized { window.deminiaturize(nil) }
        if !NSScreen.screens.contains(where: {
            let overlap = $0.visibleFrame.intersection(window.frame)
            return overlap.width >= 140 && overlap.height >= 100
        }) { window.center() }
        if NSApp.isHidden { NSApp.unhide(nil) }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate()
    }

    func applicationDidResignActive(_ notification: Notification) {
        dictation.interrupt("Dictée interrompue : NoteVive est passé à l’arrière-plan")
        if workspace.library.canEdit { _ = workspace.library.flush() }
    }

    func windowWillMiniaturize(_ notification: Notification) {
        dictation.interrupt("Dictée interrompue : la fenêtre a été réduite")
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        canCloseLibrary()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        return canCloseLibrary() ? .terminateNow : .terminateCancel
    }

    private func canCloseLibrary() -> Bool {
        if dictation.phase == .listening || dictation.phase == .loading {
            dictation.toggle()
            return false
        }
        guard dictation.canSwitchNote else { return false }
        let library = workspace.library
        guard library.canEdit else { return true }
        guard !library.flush() else { return true }
        let alert = NSAlert()
        alert.messageText = "La dernière sauvegarde a échoué"
        alert.informativeText = "Revenez à la transcription pour réessayer la sauvegarde ou exporter le texte. Si vous quittez, les modifications non enregistrées seront perdues."
        alert.addButton(withTitle: "Revenir")
        alert.addButton(withTitle: "Quitter sans enregistrer")
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
let arguments = Array(CommandLine.arguments.dropFirst())
if arguments == ["--self-test"] || arguments == ["--self-test-audio"] {
    do {
        if arguments == ["--self-test-audio"] { try audioCallbackRegression(model: model) }
        else { try selfTest(model: model) }
    }
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
