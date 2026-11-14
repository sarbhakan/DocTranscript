import Foundation

struct MedicalLexicon: Decodable, Sendable {
    struct Source: Decodable, Sendable {
        let id: String
        let edition: String?
    }

    struct Profile: Decodable, Identifiable, Sendable {
        let id: String
        let label: String
        let entries: [String]
        let active: [String]
    }

    static let maxActive = 256
    static let maxFavorites = 24
    static let maxBytes = 16 * 1024 * 1024
    static let empty = MedicalLexicon(schema: 1, profiles: [], sources: nil)

    let schema: Int
    let profiles: [Profile]
    let sources: [Source]?

    static func load(from file: URL) throws -> MedicalLexicon {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        guard let bytes = try handle.read(upToCount: maxBytes + 1), bytes.count <= maxBytes else {
            throw NoteViveError.lexicon
        }
        let catalog = try JSONDecoder().decode(Self.self, from: bytes)
        guard catalog.schema == 1, (1...32).contains(catalog.profiles.count),
              Set(catalog.profiles.map(\.id)).count == catalog.profiles.count else {
            throw NoteViveError.lexicon
        }
        for profile in catalog.profiles {
            let known = Set(profile.entries)
            guard validID(profile.id), !profile.label.isEmpty, profile.label.count <= 120,
                  (1...10_000).contains(profile.entries.count), known.count == profile.entries.count,
                  profile.entries.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 512 && !$0.contains("\n") }),
                  profile.active.count <= maxActive, Set(profile.active).count == profile.active.count,
                  profile.active.allSatisfy({ known.contains($0) && canFavor($0) }) else {
                throw NoteViveError.lexicon
            }
        }
        return catalog
    }

    static func validID(_ id: String) -> Bool {
        (1...48).contains(id.utf8.count)
            && id.utf8.allSatisfy { (97...122).contains($0) || (48...57).contains($0) || $0 == 45 }
    }

    // Deliberately keep measured values and stand-alone units out of the
    // context list. Entries with numbers remain searchable in the catalogue.
    private static let protected: Set<String> = [
            "zero", "un", "une", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
            "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize", "vingt", "trente",
            "quarante", "cinquante", "soixante", "cent", "cents", "mille", "virgule", "demi", "quart",
            "demie", "quarts", "milligramme", "milligrammes", "microgramme", "microgrammes", "gramme",
            "grammes", "millilitre", "millilitres", "litre", "litres", "nanogramme", "nanogrammes",
            "millimetre", "millimetres", "kilogramme", "kilogrammes", "mg", "ml", "mcg", "ug", "µg",
            "ui", "pas", "aucun", "aucune", "sans", "droite", "droit", "gauche", "negatif", "negative",
    ]

    static func canFavor(_ term: String) -> Bool {
        let key = term.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "fr"))
        let words = key.split { !$0.isLetter }
        guard (4...160).contains(term.utf8.count), !words.isEmpty, words.count <= 10,
              term.allSatisfy({ $0.isLetter || " -'’".contains($0) }) else { return false }
        return words.allSatisfy { !protected.contains(String($0)) }
    }

    func profile(_ id: String) -> Profile? { profiles.first { $0.id == id } }

    static func phrases(_ profile: Profile, favorites: [String]) -> [String] {
        var seen: Set<String> = []
        let known = Set(profile.entries)
        let prioritized = favorites.prefix(maxFavorites).filter { known.contains($0) && canFavor($0) }
        return Array((prioritized + profile.active).filter { seen.insert($0).inserted }.prefix(maxActive))
    }
}
