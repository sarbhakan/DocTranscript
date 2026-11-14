#ifndef NOTE_VIVE_ULTIMED_LEXICAL_CONTEXT_H
#define NOTE_VIVE_ULTIMED_LEXICAL_CONTEXT_H

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace notevive {

class LexicalContext {
public:
    static constexpr size_t none = std::numeric_limits<size_t>::max();
    static constexpr size_t maxPhrases = 10000;
    static constexpr size_t maxPhraseBytes = 192;
    static constexpr size_t maxPhraseWords = 12;
    static constexpr size_t maxInputBytes = maxPhrases * (maxPhraseBytes + 1);

    explicit LexicalContext(const std::vector<std::string> &vocabulary)
        : tokens_(vocabulary.size()) {
        for (size_t i = 0; i < vocabulary.size(); ++i) {
            auto folded = fold(vocabulary[i]);
            if (!folded.empty() && folded.front() == '<') continue; // control/byte tokens
            tokens_[i].text = std::move(folded);
            tokens_[i].protectedStart = tokens_[i].text.empty() || sensitive(trim(tokens_[i].text));
        }
    }

    // Parse once before the recording. A separate graph is built first so a
    // malformed catalogue cannot leave half of its entries active.
    int set(std::string_view lines) {
        if (lines.size() > maxInputBytes) throw std::invalid_argument("Lexical profile too large");
        std::vector<Node> graph(1);
        std::unordered_set<std::string> phrases;
        size_t count = 0;
        while (!lines.empty()) {
            const auto sep = lines.find('\n');
            auto line = trim(lines.substr(0, sep));
            if (!line.empty()) {
                if (++count > maxPhrases) throw std::invalid_argument("Too many lexical hints");
                if (line.size() <= maxPhraseBytes) {
                    auto phrase = fold(line);
                    if (safePhrase(phrase) && phrases.insert(phrase).second) {
                        size_t node = add(graph, 0, ' ');
                        for (unsigned char ch : phrase) node = add(graph, node, ch);
                        graph[node].terminal = true;
                    }
                }
            }
            if (sep == std::string_view::npos) break;
            lines.remove_prefix(sep + 1);
        }
        graph_.swap(graph);
        phrases_.swap(phrases);
        return static_cast<int>(phrases_.size());
    }

    bool enabled() const { return !phrases_.empty(); }

    size_t advance(size_t previous, int32_t token, bool startOfText, bool allowNew) const {
        const auto &piece = tokens_[token].text;
        if (piece.empty()) return none;
        if (previous != none) {
            auto next = follow(previous, piece);
            if (next != none) return next;
        }
        if (!allowNew) return none;
        if (piece.front() == ' ') return follow(0, piece);
        return startOfText ? follow(follow(0, " "), piece) : none;
    }

    int32_t suggest(size_t previous, int32_t raw, const float *logits,
                    int32_t blank, bool startOfText, bool allowNew) const {
        // Never turn a blank into a word. A hint is not sufficient reason to
        // override silence or a word with a clear acoustic advantage.
        if (raw == blank || tokens_[raw].protectedStart) return raw;
        const auto unmodified = advance(previous, raw, startOfText, allowNew);
        float best = logits[raw] + reward(previous, unmodified, tokens_[raw].text.size());
        int32_t chosen = raw;
        for (int32_t candidate = 0; candidate < blank; ++candidate) {
            if (candidate == raw || !(logits[candidate] > logits[raw] - 1.5f) ||
                tokens_[candidate].protectedStart) continue;
            const auto next = advance(previous, candidate, startOfText, allowNew);
            if (next == none) continue;
            if ((previous == none || graph_[next].depth <= graph_[previous].depth) &&
                commonPrefix(trim(tokens_[candidate].text), trim(tokens_[raw].text)) < 3) continue;
            const float score = logits[candidate] + reward(previous, next, tokens_[candidate].text.size());
            if (score > best + 0.02f) {
                best = score;
                chosen = candidate;
            }
        }
        return chosen;
    }

    // A second hypothesis is only accepted when the entire change fits one
    // complete catalogue term. Text outside the replacement (including its
    // spaces/punctuation) must be byte-for-byte equal to the ordinary decode.
    bool permits(std::string_view original, std::string_view candidate) const {
        if (original == candidate) return false;
        const auto left = words(original);
        const auto right = words(candidate);
        size_t prefix = 0;
        while (prefix < left.size() && prefix < right.size() &&
               raw(original, left[prefix]) == raw(candidate, right[prefix])) ++prefix;
        size_t suffix = 0;
        while (suffix < left.size() - prefix && suffix < right.size() - prefix &&
               raw(original, left[left.size() - 1 - suffix]) == raw(candidate, right[right.size() - 1 - suffix]))
            ++suffix;
        const size_t rightEnd = right.size() - suffix;
        if (prefix == rightEnd || prefix == left.size() - suffix ||
            rightEnd - prefix > maxPhraseWords) return false;
        for (size_t i = prefix; i < left.size() - suffix; ++i) {
            const auto part = fold(raw(original, left[i]));
            if (sensitive(part) || !safeWord(part)) return false;
        }
        const size_t earliest = rightEnd > maxPhraseWords ? rightEnd - maxPhraseWords : 0;
        for (size_t from = earliest; from <= prefix; ++from) {
            for (size_t to = rightEnd; to <= right.size() && to - from <= maxPhraseWords; ++to) {
                const auto replacement = candidate.substr(right[from].start, right[to - 1].end - right[from].start);
                if (replacement.size() > maxPhraseBytes || !phrases_.count(fold(replacement))) continue;
                const size_t otherEnd = to + left.size() - right.size();
                const auto old = original.substr(left[from].start, left[otherEnd - 1].end - left[from].start);
                if (old.size() > maxPhraseBytes || !safePhrase(fold(old)) || phrases_.count(fold(old)) ||
                    original.substr(0, left[from].start) != candidate.substr(0, right[from].start) ||
                    original.substr(left[otherEnd - 1].end) != candidate.substr(right[to - 1].end)) continue;
                if (similar(fold(old), fold(replacement))) return true;
            }
        }
        return false;
    }

private:
    struct Token { std::string text; bool protectedStart = true; };
    struct Node {
        std::unordered_map<unsigned char, size_t> children;
        size_t depth = 0;
        bool terminal = false;
    };
    struct Span { size_t start, end; };
    std::vector<Token> tokens_;
    std::vector<Node> graph_{1};
    std::unordered_set<std::string> phrases_;

    static size_t add(std::vector<Node> &graph, size_t node, unsigned char ch) {
        if (auto it = graph[node].children.find(ch); it != graph[node].children.end()) return it->second;
        const auto depth = graph[node].depth + 1;
        const auto next = graph.size();
        graph[node].children.emplace(ch, next);
        graph.push_back({{}, depth, false});
        return next;
    }

    size_t follow(size_t at, std::string_view text) const {
        if (at == none) return none;
        for (unsigned char ch : text) {
            const auto it = graph_[at].children.find(ch);
            if (it == graph_[at].children.end()) return none;
            at = it->second;
        }
        return at;
    }

    float reward(size_t previous, size_t next, size_t bytes) const {
        if (next == none) return 0.f;
        const size_t depth = graph_[next].depth;
        if (depth < 4) return 0.f;
        if (graph_[next].terminal) return 1.45f;
        if (previous != none && depth > graph_[previous].depth && depth > bytes) return 0.95f;
        return 0.30f;
    }

    static std::string_view trim(std::string_view s) {
        while (!s.empty() && (s.front() == ' ' || s.front() == '\r' || s.front() == '\t')) s.remove_prefix(1);
        while (!s.empty() && (s.back() == ' ' || s.back() == '\r' || s.back() == '\t')) s.remove_suffix(1);
        return s;
    }

    // We operate on the model's token surfaces rather than claiming to encode
    // text with SentencePiece. Case folding covers the Latin alphabet used in
    // French catalogues, and also normalizes apostrophes.
    static std::string fold(std::string_view s) {
        std::string out;
        for (size_t i = 0; i < s.size(); ++i) {
            const auto b = static_cast<unsigned char>(s[i]);
            if (b >= 'A' && b <= 'Z') out += static_cast<char>(b + 32);
            else if (i + 1 < s.size() && b == 0xc3 &&
                     static_cast<unsigned char>(s[i + 1]) >= 0x80 &&
                     static_cast<unsigned char>(s[i + 1]) <= 0x9e && s[i + 1] != '\x97') {
                out += s[i];
                out += static_cast<char>(static_cast<unsigned char>(s[++i]) + 32);
            } else if (s.substr(i, 2) == "\xc5\x92") {
                out += "\xc5\x93";
                ++i;
            } else if (s.substr(i, 3) == "\xe2\x80\x99") {
                out += '\'';
                i += 2;
            } else out += s[i];
        }
        return out;
    }

    static bool latin(std::string_view s, size_t &i) {
        const auto b = static_cast<unsigned char>(s[i]);
        if (b >= 'a' && b <= 'z') return true;
        if (i + 1 >= s.size()) return false;
        const auto c = static_cast<unsigned char>(s[i + 1]);
        if ((b == 0xc3 && c >= 0xa0 && c <= 0xbf && c != 0xb7) ||
            (b == 0xc5 && c == 0x93)) {
            ++i;
            return true;
        }
        return false;
    }

    static bool sensitive(std::string_view s) {
        static const std::unordered_set<std::string_view> guarded{
            "zéro", "zero", "un", "une", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
            "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize", "vingt", "trente", "quarante",
            "cinquante", "soixante", "cent", "cents", "mille", "million", "millions", "milliard", "milliards",
            "virgule", "demi", "demie", "demis", "demies", "quart", "quarts", "tiers", "moitié", "douzaine",
            "premier", "première", "second", "seconde", "deuxième", "troisième", "quatrième", "cinquième",
            "sixième", "septième", "huitième", "neuvième", "dixième", "centième", "millième",
            "non", "ne", "pas", "plus", "ni", "sans", "jamais", "aucun", "aucune", "absence", "négatif",
            "négative", "négatifs", "négatives", "négativité", "positif", "positive", "positifs", "positives",
            "absent", "absente", "absents", "absentes", "présent", "présente", "présents", "présentes",
            "exclu", "exclue", "exclus", "exclues", "confirmé", "confirmée", "confirmés", "confirmées",
            "droit", "droite", "droits", "droites", "gauche", "gauches", "bilatéral", "bilatérale", "latéralité",
            "mg", "g", "kg", "µg", "μg", "mcg", "ng", "ml", "cl", "dl", "l", "mm", "cm", "m", "ui",
            "milligramme", "milligrammes", "microgramme", "microgrammes", "nanogramme", "nanogrammes",
            "gramme", "grammes", "kilogramme", "kilogrammes", "millilitre", "millilitres", "centilitre",
            "centilitres", "litre", "litres", "millimètre", "millimètres", "centimètre", "centimètres",
            "mètre", "mètres", "mmol", "mol", "mole", "moles", "millimole", "millimoles", "centimole",
            "micromole", "micromoles", "unité", "unités", "pourcentage", "internationales", "mercure",
            "décilitre", "décilitres", "nanolitre", "nanolitres", "microlitre", "microlitres", "milliseconde",
            "millisecondes", "micromètre", "micromètres", "nanomètre", "nanomètres", "goutte", "gouttes",
            "kilocalorie", "kilocalories", "milléquivalent", "milléquivalents", "milliosmole", "milliosmoles",
            "heure", "heures", "minute", "minutes", "jour", "jours", "semaine", "semaines", "mois", "ans",
            "matin", "soir", "fois", "comprimé", "comprimés", "gélule", "gélules", "bouffée", "bouffées",
        };
        return guarded.count(s) || s.rfind("n'", 0) == 0 ||
            std::any_of(s.begin(), s.end(), [](char c) { return c >= '0' && c <= '9'; });
    }

    static bool safeWord(std::string_view s) {
        if (s.empty() || s.front() == '-' || s.front() == '\'' || s.back() == '-' || s.back() == '\'') return false;
        for (size_t i = 0; i < s.size(); ++i) {
            if (s[i] == '-' || s[i] == '\'') {
                // Reject compounds that could hide e.g. vingt-cinq or non-actif.
                if (i == 0 || i + 1 >= s.size() || sensitive(s.substr(0, i)) || sensitive(s.substr(i + 1)))
                    return false;
            } else if (!latin(s, i)) return false;
        }
        return !sensitive(s);
    }

    static bool safePhrase(std::string_view s) {
        if (s.size() < 4 || s.size() > maxPhraseBytes) return false;
        size_t count = 0;
        while (!s.empty()) {
            const size_t n = s.find(' ');
            if (++count > maxPhraseWords || !safeWord(s.substr(0, n))) return false;
            if (n == std::string_view::npos) return true;
            s.remove_prefix(n + 1);
        }
        return false;
    }

    static std::vector<Span> words(std::string_view s) {
        std::vector<Span> result;
        auto core = [](unsigned char c) {
            return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                   (c >= '0' && c <= '9') || c >= 0x80 || c == '-' || c == '\'';
        };
        for (size_t i = 0; i < s.size();) {
            if (!core(static_cast<unsigned char>(s[i]))) {
                ++i;
                continue;
            }
            const size_t start = i++;
            while (i < s.size() && core(static_cast<unsigned char>(s[i]))) ++i;
            result.push_back({start, i});
        }
        return result;
    }

    static std::string_view raw(std::string_view s, Span span) {
        return s.substr(span.start, span.end - span.start);
    }

    static size_t commonPrefix(std::string_view a, std::string_view b) {
        size_t letters = 0;
        for (size_t i = 0; i < std::min(a.size(), b.size()) && a[i] == b[i]; ++i) {
            const auto ch = static_cast<unsigned char>(a[i]);
            if ((ch & 0xc0) != 0x80 && ch != ' ' && ch != '-' && ch != '\'') ++letters;
        }
        return letters;
    }

    static bool similar(std::string a, std::string b) {
        auto lettersOnly = [](std::string &s) {
            s.erase(std::remove_if(s.begin(), s.end(), [](char c) {
                return c == ' ' || c == '-' || c == '\'';
            }), s.end());
        };
        lettersOnly(a);
        lettersOnly(b);
        if (std::min(a.size(), b.size()) < 4 || commonPrefix(a, b) < 2) return false;
        const auto cap = std::min<size_t>(4, std::max(a.size(), b.size()) / 3);
        if (a.size() > b.size() + cap || b.size() > a.size() + cap) return false;
        std::vector<size_t> row(b.size() + 1);
        for (size_t j = 0; j <= b.size(); ++j) row[j] = j;
        for (size_t i = 1; i <= a.size(); ++i) {
            auto diag = row[0];
            row[0] = i;
            for (size_t j = 1; j <= b.size(); ++j) {
                auto prior = row[j];
                row[j] = std::min({row[j] + 1, row[j - 1] + 1, diag + (a[i - 1] != b[j - 1])});
                diag = prior;
            }
        }
        return row.back() <= cap;
    }
};
} // namespace notevive

#endif
