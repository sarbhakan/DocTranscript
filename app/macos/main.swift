import AppKit
import SwiftUI

@MainActor final class Application: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let dictation: Dictation
    let workspace: TranscriptWorkspace
    private var window: NSWindow?
    private var sleepObserver: NSObjectProtocol?

    init(model: URL, lexiconFile: URL) {
        let dictation = Dictation(model: model, lexiconFile: lexiconFile)
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

    private func preferredContentSize(on screen: NSScreen?) -> NSSize {
        let available = screen?.visibleFrame.size ?? NSSize(width: 1_035, height: 655)
        return NSSize(width: min(995, max(1, available.width - 40)),
                      height: min(615, max(1, available.height - 60)))
    }

    private func makeMainWindow() -> NSWindow {
        let size = preferredContentSize(on: NSScreen.main)
        let contentRect = NSRect(origin: .zero, size: size)
        let newWindow = NSWindow(
            contentRect: contentRect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        newWindow.title = "NoteVive · Dictée locale"
        // AppKit owns the window's size. The flexible SwiftUI split view should
        // fill it, rather than using its initial fitting size to shrink it.
        let container = NSView(frame: contentRect)
        let host = NSHostingView(rootView: LibraryView(workspace: workspace))
        host.sizingOptions = []
        host.frame = container.bounds
        host.autoresizingMask = [.width, .height]
        container.addSubview(host)
        newWindow.contentView = container
        newWindow.contentMinSize = NSSize(width: min(740, size.width), height: min(500, size.height))
        newWindow.setContentSize(size)
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
        let minimum = window.contentMinSize
        let content = window.contentRect(forFrameRect: window.frame).size
        let mustResize = content.width < minimum.width || content.height < minimum.height
        if mustResize { window.setContentSize(preferredContentSize(on: window.screen ?? NSScreen.main)) }
        if mustResize || !NSScreen.screens.contains(where: {
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

private let maxWAVBytes = 20 * 1024 * 1024

private func readTestWAV() throws -> Data {
    // The caller opens the file; passing bytes on stdin keeps the sandbox in force.
    var data = Data()
    while let chunk = try FileHandle.standardInput.read(upToCount: 65_536), !chunk.isEmpty {
        guard chunk.count <= maxWAVBytes - data.count else { throw NoteViveError.audio }
        data.append(chunk)
    }
    return data
}

private func decodeWAV(_ data: Data) throws -> (samples: [Float], rate: Int32) {
    return try data.withUnsafeBytes { (bytes: UnsafeRawBufferPointer) in
        func word(_ offset: Int) -> UInt16 {
            UInt16(littleEndian: bytes.loadUnaligned(fromByteOffset: offset, as: UInt16.self))
        }
        func dword(_ offset: Int) -> UInt32 {
            UInt32(littleEndian: bytes.loadUnaligned(fromByteOffset: offset, as: UInt32.self))
        }
        guard bytes.count >= 12, dword(0) == 0x46464952, dword(8) == 0x45564157 else {
            throw NoteViveError.audio
        }
        let end = Int(dword(4)) + 8
        guard (12...bytes.count).contains(end) else { throw NoteViveError.audio }
        var position = 12
        var rate: Int32?
        var payload: Range<Int>?
        while end - position >= 8 {
            let length = Int(dword(position + 4))
            let start = position + 8
            guard length <= end - start else { throw NoteViveError.audio }
            switch dword(position) {
            case 0x20746d66: // fmt
                guard length >= 16, rate == nil, word(start) == 1, word(start + 2) == 1,
                      word(start + 12) == 2, word(start + 14) == 16,
                      (8_000...192_000).contains(dword(start + 4)) else { throw NoteViveError.audio }
                rate = Int32(dword(start + 4))
            case 0x61746164: // data
                guard payload == nil, length >= 2, length.isMultiple(of: 2) else { throw NoteViveError.audio }
                payload = start..<(start + length)
            default: break
            }
            position = start + length + (length & 1)
            guard position <= end else { throw NoteViveError.audio }
        }
        guard position == end, let rate, let payload, payload.count / 2 <= Int(rate) * 300 else {
            throw NoteViveError.audio
        }
        let samples = stride(from: payload.lowerBound, to: payload.upperBound, by: 2)
            .map { Float(Int16(bitPattern: word($0))) / 32_768 }
        return (samples, rate)
    }
}

private func selfTest(model: URL) throws {
    let (samples, rate) = try decodeWAV(readTestWAV())
    let result = try replayDictation(worker: RecognitionWorker(model: model), samples: samples, rate: rate)
    let paused = result.pause.filter { !$0.text.isEmpty }
    let stopped = result.stop.filter { !$0.text.isEmpty }
    print("segments_pause=\(paused.count)")
    for (index, phrase) in paused.enumerated() {
        print("pause[\(index + 1)]=\(phrase.text)")
        print("audio_ms[\(index + 1)]=\(phrase.audio_ms ?? 0)")
    }
    print("segments_arret=\(stopped.count)")
    for (index, phrase) in stopped.enumerated() { print("arret[\(index + 1)]=\(phrase.text)") }
    print("texte=\((paused + stopped).map(\.text).joined(separator: " "))")
}

private func benchmark(model: URL, lexiconFile: URL) throws {
    struct Failure: Encodable { let error: String }
    let input = FileHandle.standardInput
    let output = FileHandle.standardOutput
    let encoder = JSONEncoder()
    let worker = RecognitionWorker(model: model)
    let lexicon = try MedicalLexicon.load(from: lexiconFile)

    func exact(_ size: Int) throws -> Data {
        var data = Data()
        data.reserveCapacity(size)
        while data.count < size {
            guard let chunk = try input.read(upToCount: min(65_536, size - data.count)), !chunk.isEmpty else {
                throw NoteViveError.audio
            }
            data.append(chunk)
        }
        return data
    }

    func write<T: Encodable>(_ object: T) throws {
        var bytes = try encoder.encode(object)
        bytes.append(10)
        try output.write(contentsOf: bytes)
    }

    while true {
        var idBytes = Data()
        while true {
            guard let byte = try input.read(upToCount: 1)?.first else {
                if idBytes.isEmpty { return }
                throw NoteViveError.lexicon
            }
            if byte == 10 { break }
            guard idBytes.count < 53 else { throw NoteViveError.lexicon }
            idBytes.append(byte)
        }
        let size = Int(try exact(4).withUnsafeBytes { UInt32(littleEndian: $0.loadUnaligned(as: UInt32.self)) })
        guard size <= maxWAVBytes else { throw NoteViveError.audio }
        let bytes = try exact(size)
        do {
            guard let id = String(data: idBytes, encoding: .utf8) else { throw NoteViveError.lexicon }
            let full = id.hasPrefix("full:")
            let profile = lexicon.profile(full ? String(id.dropFirst(5)) : id)
            guard id.isEmpty || profile != nil else { throw NoteViveError.lexicon }
            let selecting = DispatchTime.now().uptimeNanoseconds
            let phrases = (full ? profile?.entries.filter(MedicalLexicon.canFavor) : profile?.active) ?? []
            let selectionMS = Double(DispatchTime.now().uptimeNanoseconds - selecting) / 1e6
            let (samples, rate) = try decodeWAV(bytes)
            try write(replayDictation(worker: worker, samples: samples, rate: rate, profile: id,
                                      phrases: phrases, selectionMS: selectionMS))
        } catch { try write(Failure(error: error.localizedDescription)) }
    }
}

let resources = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources", isDirectory: true)
let model = resources.appendingPathComponent("Model", isDirectory: true)
let lexiconFile = resources.appendingPathComponent("Lexique/profiles.json")
let arguments = Array(CommandLine.arguments.dropFirst())
if arguments == ["--self-test"] || arguments == ["--self-test-audio"] || arguments == ["--lexicon-bench"] {
    do {
        if arguments == ["--self-test-audio"] { try audioCallbackRegression(model: model) }
        else if arguments == ["--lexicon-bench"] { try benchmark(model: model, lexiconFile: lexiconFile) }
        else { try selfTest(model: model) }
    }
    catch {
        FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8))
        exit(1)
    }
} else {
    MainActor.assumeIsolated {
        let app = NSApplication.shared
        let delegate = Application(model: model, lexiconFile: lexiconFile)
        app.setActivationPolicy(.regular)
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
