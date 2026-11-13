import Foundation

@main struct LibraryTests {
    @MainActor static func main() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("notevive-library-tests-\(UUID())", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }

        try persistence(in: directory.appendingPathComponent("persistence"))
        try recovery(in: directory.appendingPathComponent("recovery"))
        try blockedSave(in: directory.appendingPathComponent("blocked-save"))
        try newerFormat(in: directory.appendingPathComponent("newer-format"))
        try await delayedEdit(in: directory.appendingPathComponent("delayed-edit"))
        print("5 contrôles de bibliothèque réussis.")
    }

    @MainActor static func persistence(in directory: URL) throws {
        var now = Date(timeIntervalSinceReferenceDate: 1_000)
        var library: TranscriptLibrary? = TranscriptLibrary(directory: directory, clock: { now })
        guard let folderID = library?.createFolder(name: "  Dossiers fictifs  "),
              let noteID = library?.createNote(),
              let otherID = library?.createNote(folderID: folderID) else { fatalError("création") }
        check(library?.createFolder(name: "dossiers fictifs") == nil, "unicité du nom")
        check(library?.renameNote(noteID, title: "Cheville — essai") == true, "renommer")
        check(library?.moveNote(noteID, to: UUID()) == false, "dossier inexistant refusé")
        check(library?.moveNote(noteID, to: folderID) == true, "déplacer")
        check(library?.renameFolder(folderID, name: "Consultations fictives") == true, "renommer dossier")
        now.addTimeInterval(60)
        check(library?.updateBody(noteID, body: "Pas de douleur.\nTexte fictif.") == true, "modifier le texte")
        check(library?.moveNote(otherID, to: nil) == true, "retirer du dossier")

        let competing = TranscriptLibrary(directory: directory)
        check(!competing.canEdit && competing.status == .unavailable, "un deuxième processus ne peut pas écrire")
        check(competing.createNote() == nil, "le verrou ne permet pas d'écriture")
        library = nil

        let reopened = TranscriptLibrary(directory: directory)
        check(reopened.status == .saved, "réouverture")
        check(reopened.note(noteID)?.title == "Cheville — essai", "titre restauré")
        check(reopened.note(noteID)?.body == "Pas de douleur.\nTexte fictif.", "corps restauré")
        check(reopened.note(noteID)?.folderID == folderID, "dossier restauré")
        check(reopened.note(otherID)?.folderID == nil, "note sans dossier")
        check(reopened.note(noteID)?.createdAt == now.addingTimeInterval(-60), "date de création")
        check(reopened.note(noteID)?.updatedAt == now, "date de modification")
        check(reopened.folders.map(\.name) == ["Consultations fictives"], "dossier renommé restauré")
        let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
        check((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o700, "dossier privé")
    }

    @MainActor static func recovery(in directory: URL) throws {
        var original: TranscriptLibrary? = TranscriptLibrary(directory: directory)
        guard let id = original?.createNote() else { fatalError("création") }
        original?.updateBody(id, body: "Dernière copie de secours")
        original?.updateBody(id, body: "Copie la plus récente")
        original = nil

        let primary = directory.appendingPathComponent("transcriptions.json")
        let backup = directory.appendingPathComponent("transcriptions.backup.json")
        let broken = Data("copie endommagée".utf8)
        // Replace the file rather than editing it in place, matching storage commits.
        try broken.write(to: primary, options: .atomic)
        var recovered: TranscriptLibrary? = TranscriptLibrary(directory: directory)
        check(recovered?.status == .recovered, "restauration détectée")
        check(recovered?.note(id)?.body == "Dernière copie de secours", "contenu de la copie de secours")
        recovered = nil

        var reopened: TranscriptLibrary? = TranscriptLibrary(directory: directory)
        check(reopened?.status == .saved && reopened?.note(id) != nil, "restauration persistante")
        reopened = nil

        try broken.write(to: primary, options: .atomic)
        try broken.write(to: backup, options: .atomic)
        let unavailable = TranscriptLibrary(directory: directory)
        check(!unavailable.canEdit && unavailable.status == .unavailable, "double corruption protégée")
        check(unavailable.createNote() == nil, "pas de réinitialisation silencieuse")
        let retained = try Data(contentsOf: primary)
        check(retained == broken, "fichier invalide conservé")
    }

    @MainActor static func blockedSave(in directory: URL) throws {
        let library = TranscriptLibrary(directory: directory)
        let primary = directory.appendingPathComponent("transcriptions.json")
        try FileManager.default.createDirectory(at: primary, withIntermediateDirectories: false)
        guard let id = library.createNote() else { fatalError("création en mémoire") }
        library.updateBody(id, body: "Texte encore en mémoire")
        check(library.status == .unsaved, "panne d'écriture signalée")
        check(library.note(id)?.body == "Texte encore en mémoire", "modifications retenues")
        try FileManager.default.removeItem(at: primary)
        check(library.flush(), "réessai réussi")
        check(library.status == .saved, "sauvegarde confirmée")
        let data = try Data(contentsOf: primary)
        check(String(decoding: data, as: UTF8.self).contains("Texte encore en mémoire"), "contenu écrit")
    }

    @MainActor static func newerFormat(in directory: URL) throws {
        var original: TranscriptLibrary? = TranscriptLibrary(directory: directory)
        guard let id = original?.createNote() else { fatalError("création") }
        original?.updateBody(id, body: "Une sauvegarde ancienne existe")
        original = nil

        let primary = directory.appendingPathComponent("transcriptions.json")
        let newer = Data(#"{"version":999,"data":"ne pas écraser"}"#.utf8)
        try newer.write(to: primary, options: .atomic)
        let unavailable = TranscriptLibrary(directory: directory)
        check(!unavailable.canEdit, "une version plus récente n'est pas remplacée par une copie antérieure")
        let retained = try Data(contentsOf: primary)
        check(retained == newer, "version récente préservée")
    }

    @MainActor static func delayedEdit(in directory: URL) async throws {
        var library: TranscriptLibrary? = TranscriptLibrary(directory: directory, saveDelay: .milliseconds(10))
        guard let id = library?.createNote() else { fatalError("création") }
        library?.updateBody(id, body: "Édition rapide", immediate: false)
        check(library?.status == .pending, "édition placée en attente")
        library?.updateBody(id, body: "Dernière édition rapide", immediate: false)
        let deadline = ContinuousClock.now + .seconds(2)
        while library?.status == .pending && ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(10))
        }
        check(library?.status == .saved, "écriture différée achevée")
        library?.updateBody(id, body: "Dernière édition à la fermeture", immediate: false)
        check(library?.status == .pending, "édition avant fermeture en attente")
        check(library?.flush() == true, "fermeture écrit immédiatement")
        library = nil
        let reopened = TranscriptLibrary(directory: directory)
        check(reopened.note(id)?.body == "Dernière édition à la fermeture", "texte confirmé")
    }

    static func check(_ result: @autoclosure () -> Bool, _ label: String) {
        guard result() else { fatalError(label) }
    }
}
