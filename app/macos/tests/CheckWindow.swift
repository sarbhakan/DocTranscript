import AppKit
import CoreGraphics

// Run with NoteVive already open on the current desktop. Only the process ID,
// position, size and WindowServer visibility of NoteVive windows are examined.
let bundleID = "fr.notevive.prototype.macos"
let minimumWidth: CGFloat = 700
let minimumHeight: CGFloat = 470

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

let processes = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
let pids = Set(processes.filter { !$0.isTerminated }.map(\.processIdentifier))
guard !pids.isEmpty else { fail("NoteVive n’est pas lancé.") }

// WindowServer and CGDisplayBounds use the same top-left-based coordinate
// system, unlike the AppKit coordinate system of NSScreen.frame.
let screenNumber = NSDeviceDescriptionKey("NSScreenNumber")
let displayFrames = NSScreen.screens.compactMap { screen -> CGRect? in
    guard let id = screen.deviceDescription[screenNumber] as? NSNumber else { return nil }
    return CGDisplayBounds(id.uint32Value)
}
guard !displayFrames.isEmpty else { fail("Aucun écran détecté dans la session graphique.") }

let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
guard let windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
    fail("Impossible de vérifier les fenêtres dans cette session graphique.")
}

let frames: [CGRect] = windows.compactMap { window in
    guard let pid = window[kCGWindowOwnerPID as String] as? NSNumber, pids.contains(pid.int32Value),
          let layer = window[kCGWindowLayer as String] as? NSNumber, layer.intValue == 0,
          let visible = window[kCGWindowIsOnscreen as String] as? NSNumber, visible.boolValue,
          let alpha = window[kCGWindowAlpha as String] as? NSNumber, alpha.doubleValue > 0,
          let bounds = window[kCGWindowBounds as String] as? [String: Any] else { return nil }
    return CGRect(dictionaryRepresentation: bounds as CFDictionary)
}

for frame in frames {
    if displayFrames.contains(where: { screen in
        let intersection = screen.intersection(frame)
        return intersection.width >= minimumWidth && intersection.height >= minimumHeight
    }) {
        print("Fenêtre NoteVive visible : \(Int(frame.width)) × \(Int(frame.height)) points.")
        exit(0)
    }
}

let sizes = frames.map { "\(Int($0.width)) × \(Int($0.height))" }.joined(separator: ", ")
fail("Aucune fenêtre NoteVive d’au moins 700 × 470 points sur un écran. Tailles observées : \(sizes.isEmpty ? "aucune" : sizes).")
