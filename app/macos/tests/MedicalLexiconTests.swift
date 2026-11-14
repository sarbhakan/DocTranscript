import Foundation

// The catalogue parser uses the same user-facing error in the app.
enum NoteViveError: Error { case lexicon }

@main struct MedicalLexiconTests {
    static func main() throws {
        let fixture = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: fixture) }
        func load(_ entries: [String], _ active: [String]) throws -> MedicalLexicon {
            let profile: [String: Any] = ["id": "hematologie", "label": "Hématologie",
                                          "entries": entries, "active": active]
            try JSONSerialization.data(withJSONObject: ["schema": 1, "profiles": [profile]]).write(to: fixture)
            return try MedicalLexicon.load(from: fixture)
        }
        let entries = ["caplacizumab", "hémoglobinurie paroxystique nocturne", "0,3 mL", "un demi comprimé",
                       "pas de thrombopénie", "douleur à droite"]
        let loaded = try load(entries, ["caplacizumab"])
        let profile = loaded.profile("hematologie")!
        precondition(profile.entries.count == entries.count)
        precondition(MedicalLexicon.phrases(profile, favorites: [
            "hémoglobinurie paroxystique nocturne", "caplacizumab", "0,3 mL", "pas de thrombopénie",
            "douleur à droite", "mot hors catalogue", "un demi comprimé"
        ]) == ["hémoglobinurie paroxystique nocturne", "caplacizumab"])
        for invalid in [["0,3 mL"], ["introuvable"], ["caplacizumab", "caplacizumab"]] {
            do {
                _ = try load(entries, invalid)
                fatalError("Profil invalide accepté")
            } catch NoteViveError.lexicon {}
        }
        print("Validation du lexique et priorité des favoris : OK")
    }
}
