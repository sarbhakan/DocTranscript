#pragma once

// Shared by the Windows store and the standalone portable regression tests.
#include "notes.h"

#include <algorithm>
#include <cstdint>
#include <iterator>
#include <string_view>
#include <unordered_map>
#include <utility>

namespace notes::model {

using Byte = std::uint8_t;
inline constexpr std::size_t kDateSize = 24;
inline constexpr std::size_t kIdSize = 36;
inline constexpr std::size_t kMaxBlob = 1024 * 1024;

inline bool IsId(std::wstring_view id) {
    if (id.size() != kIdSize) return false;
    for (std::size_t i = 0; i < id.size(); ++i) {
        const wchar_t ch = id[i];
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (ch != L'-') return false;
        } else if (!((ch >= L'0' && ch <= L'9') || (ch >= L'a' && ch <= L'f'))) return false;
    }
    return true;
}

// The persisted format is UTF-16LE on every platform.
inline bool IsUnicode(std::wstring_view text, bool multiline) {
    for (std::size_t i = 0; i < text.size(); ++i) {
        const auto ch = static_cast<std::uint32_t>(text[i]);
        if ((ch < 32 && !(multiline && (ch == 9 || ch == 10 || ch == 13))) ||
            (ch >= 0x7f && ch <= 0x9f) || ch > 0x10ffff) return false;
        if (ch >= 0xd800 && ch <= 0xdbff) {
            if (++i == text.size() || text[i] < 0xdc00 || text[i] > 0xdfff) return false;
        } else if (ch >= 0xdc00 && ch <= 0xdfff) return false;
    }
    return true;
}

inline bool IsDate(std::wstring_view date) {
    if (date.size() != kDateSize || date[4] != L'-' || date[7] != L'-' || date[10] != L'T' ||
        date[13] != L':' || date[16] != L':' || date[19] != L'.' || date[23] != L'Z') return false;
    const auto number = [&](std::size_t offset, std::size_t count) {
        int value = 0;
        for (std::size_t i = offset; i < offset + count; ++i) {
            if (date[i] < L'0' || date[i] > L'9') return -1;
            value = value * 10 + static_cast<int>(date[i] - L'0');
        }
        return value;
    };
    const int year = number(0, 4), month = number(5, 2), day = number(8, 2),
              hour = number(11, 2), minute = number(14, 2), second = number(17, 2),
              millisecond = number(20, 3);
    if (year < 1601 || month < 1 || month > 12 || day < 1 || hour < 0 || hour > 23 ||
        minute < 0 || minute > 59 || second < 0 || second > 59 || millisecond < 0) return false;
    constexpr int days[]{31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    const bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    return day <= days[month - 1] + (month == 2 && leap ? 1 : 0);
}

inline bool Space(wchar_t ch) {
    return ch == L' ' || (ch >= L'\t' && ch <= L'\r') || ch == L'\u00a0' || ch == L'\u1680' ||
           (ch >= L'\u2000' && ch <= L'\u200a') || ch == L'\u2028' || ch == L'\u2029' ||
           ch == L'\u202f' || ch == L'\u205f' || ch == L'\u3000';
}

inline bool FolderTitle(std::wstring_view title) {
    return !title.empty() && title.size() <= kMaxTitle && IsUnicode(title, false) &&
        std::any_of(title.begin(), title.end(), [](wchar_t ch) { return !Space(ch); });
}

inline std::wstring Fold(std::wstring_view text) {
    std::wstring result;
    result.reserve(text.size());
    for (wchar_t c : text) {
        if (c >= 0x300 && c <= 0x36f) continue; // Decomposed accents.
        if (Space(c)) {
            if (!result.empty() && result.back() != L' ') result.push_back(L' ');
            continue;
        }
        if (c >= L'A' && c <= L'Z') c += L'a' - L'A';
        else switch (c) {
            case L'à': case L'À': case L'á': case L'Á': case L'â': case L'Â':
            case L'ä': case L'Ä': case L'ã': case L'Ã': case L'å': case L'Å': c = L'a'; break;
            case L'ç': case L'Ç': c = L'c'; break;
            case L'é': case L'É': case L'è': case L'È': case L'ê': case L'Ê':
            case L'ë': case L'Ë': c = L'e'; break;
            case L'í': case L'Í': case L'ì': case L'Ì': case L'î': case L'Î':
            case L'ï': case L'Ï': c = L'i'; break;
            case L'ñ': case L'Ñ': c = L'n'; break;
            case L'ó': case L'Ó': case L'ò': case L'Ò': case L'ô': case L'Ô':
            case L'ö': case L'Ö': case L'õ': case L'Õ': case L'ø': case L'Ø': c = L'o'; break;
            case L'ú': case L'Ú': case L'ù': case L'Ù': case L'û': case L'Û':
            case L'ü': case L'Ü': c = L'u'; break;
            case L'ÿ': case L'Ÿ': case L'ý': case L'Ý': c = L'y'; break;
            case L'œ': case L'Œ': result.push_back(L'o'); c = L'e'; break;
            case L'æ': case L'Æ': result.push_back(L'a'); c = L'e'; break;
            case L'’': case L'ʼ': c = L'\''; break;
            default: break;
        }
        result.push_back(c);
    }
    if (!result.empty() && result.back() == L' ') result.pop_back();
    return result;
}

class FolderIndex {
public:
    explicit FolderIndex(const std::vector<Folder>& folders) {
        for (const auto& folder : folders) entries_.emplace(std::wstring_view(folder.id), &folder);
    }

    const Folder* Find(std::wstring_view id) const {
        auto it = entries_.find(id);
        return it == entries_.end() ? nullptr : it->second;
    }

    // Top-level files are one level deep. Returns false on a broken, cyclic,
    // or too deep chain; no recursion is needed even for corrupt inputs.
    bool Chain(std::wstring_view id, std::vector<const Folder*>& out) const {
        out.clear();
        while (!id.empty()) {
            const auto* current = Find(id);
            if (!current || out.size() == kMaxFolderDepth ||
                std::find(out.begin(), out.end(), current) != out.end()) return false;
            out.push_back(current);
            id = current->parent_id;
        }
        return true;
    }

private:
    std::unordered_map<std::wstring_view, const Folder*> entries_;
};

inline bool RepairFolderView(std::vector<Folder>& folders) {
    const FolderIndex index(folders);
    std::vector<const Folder*> chain;
    std::vector<Folder*> broken;
    for (auto& folder : folders)
        if (!index.Chain(folder.id, chain)) broken.push_back(&folder);
    // Change view only; a damaged sidecar must never trigger silent rewrites.
    for (auto* folder : broken) folder->parent_id.clear();
    return broken.empty();
}

enum class MoveResult { Ok, MissingParent, Cycle, TooDeep };

inline MoveResult CheckFolderMove(const Folder& moved, const std::vector<Folder>& existing) {
    const FolderIndex old(existing);
    std::vector<const Folder*> chain;
    if (!old.Chain(moved.parent_id, chain)) return MoveResult::MissingParent;
    if (moved.parent_id == moved.id || std::any_of(chain.begin(), chain.end(), [&](const Folder* folder) {
        return folder->id == moved.id;
    })) return MoveResult::Cycle;

    // Traverse the raw descendants of the moved folder to calculate the new
    // depth of every affected record, including any previously orphaned child.
    std::unordered_multimap<std::wstring_view, std::wstring_view> children;
    for (const auto& folder : existing)
        if (folder.id != moved.id) children.emplace(folder.parent_id, folder.id);
    std::vector<std::pair<std::wstring_view, std::size_t>> work{{moved.id, chain.size() + 1}};
    while (!work.empty()) {
        const auto [id, depth] = work.back();
        work.pop_back();
        if (depth > kMaxFolderDepth) return MoveResult::TooDeep;
        const auto [start, end] = children.equal_range(id);
        for (auto it = start; it != end; ++it) work.emplace_back(it->second, depth + 1);
    }
    return MoveResult::Ok;
}

inline bool MatchFolder(const Query& query, const Note& note, const FolderIndex& folders) {
    if (!query.filter_folder || (query.folder_id.empty() && query.include_descendants)) return true;
    if (note.folder_id == query.folder_id) return true;
    const auto* folder = folders.Find(note.folder_id);
    if (!folder) return query.folder_id.empty(); // Recover visibility of orphan notes at root.
    if (!query.include_descendants) return false;
    std::vector<const Folder*> chain;
    if (!folders.Chain(note.folder_id, chain)) return false;
    return std::any_of(chain.begin(), chain.end(), [&](const Folder* parent) { return parent->id == query.folder_id; });
}

inline std::wstring ViewPath(const std::vector<Folder>& folders, const std::wstring& id) {
    const FolderIndex index(folders);
    std::vector<const Folder*> chain;
    std::wstring result;
    if (!index.Chain(id, chain)) return result;
    for (auto it = chain.rbegin(); it != chain.rend(); ++it) {
        if (!result.empty()) result += L" / ";
        result += (*it)->title;
    }
    return result;
}

inline bool MatchText(std::wstring_view needle, const Note& note) {
    return needle.empty() || Fold(note.title).find(needle) != std::wstring::npos ||
           Fold(note.text).find(needle) != std::wstring::npos;
}

inline void OrderNotes(std::vector<Note>& notes, Sort sort) {
    if (sort == Sort::TitleAscending) {
        std::unordered_map<std::wstring, std::wstring> titles;
        titles.reserve(notes.size());
        for (const auto& note : notes) titles.emplace(note.id, Fold(note.title));
        std::sort(notes.begin(), notes.end(), [&](const Note& a, const Note& b) {
            const auto& ta = titles.at(a.id);
            const auto& tb = titles.at(b.id);
            return ta == tb ? a.id < b.id : ta < tb;
        });
    } else {
        std::sort(notes.begin(), notes.end(), [&](const Note& a, const Note& b) {
            const auto& da = sort == Sort::CreatedNewest ? a.created : a.modified;
            const auto& db = sort == Sort::CreatedNewest ? b.created : b.modified;
            return da == db ? a.id < b.id : da > db;
        });
    }
}

inline void EncodeField(std::vector<Byte>& out, std::wstring_view value) {
    std::uint32_t length = 0;
    for (const auto ch : value) length += static_cast<std::uint32_t>(ch) > 0xffff ? 2 : 1;
    for (unsigned shift = 0; shift < 32; shift += 8) out.push_back(static_cast<Byte>(length >> shift));
    auto unit = [&](std::uint32_t code) {
        out.push_back(static_cast<Byte>(code));
        out.push_back(static_cast<Byte>(code >> 8));
    };
    for (auto c : value) {
        auto ch = static_cast<std::uint32_t>(c);
        if (ch > 0xffff) {
            ch -= 0x10000;
            unit(0xd800 + (ch >> 10));
            unit(0xdc00 + (ch & 0x3ff));
        } else unit(ch);
    }
}

inline bool DecodeField(const Byte*& cursor, const Byte* end, std::wstring& value, std::size_t limit,
                        bool multiline = false, bool keep = true) {
    if (end - cursor < 4) return false;
    std::uint32_t length = 0;
    for (unsigned shift = 0; shift < 32; shift += 8) length |= static_cast<std::uint32_t>(*cursor++) << shift;
    if (length > limit || static_cast<std::size_t>(end - cursor) / 2 < length) return false;
    const Byte* field_end = cursor + length * 2;
    value.clear();
    if (keep) value.reserve(length);
    auto unit = [&]() {
        auto ch = static_cast<std::uint32_t>(cursor[0]) | (static_cast<std::uint32_t>(cursor[1]) << 8);
        cursor += 2;
        return ch;
    };
    while (cursor < field_end) {
        const auto ch = unit();
        if (ch >= 0xd800 && ch <= 0xdbff) {
            if (cursor == field_end) return false;
            const auto low = unit();
            if (low < 0xdc00 || low > 0xdfff) return false;
            if (!keep) continue;
            if constexpr (sizeof(wchar_t) == 2) {
                value.push_back(static_cast<wchar_t>(ch));
                value.push_back(static_cast<wchar_t>(low));
            } else value.push_back(static_cast<wchar_t>(0x10000 + ((ch - 0xd800) << 10) + (low - 0xdc00)));
        } else if ((ch >= 0xdc00 && ch <= 0xdfff) ||
            (ch < 32 && !(multiline && (ch == 9 || ch == 10 || ch == 13))) ||
            (ch >= 0x7f && ch <= 0x9f)) return false;
        else if (keep) value.push_back(static_cast<wchar_t>(ch));
    }
    return true;
}

inline void EncodeNote(std::vector<Byte>& out, const Note& note, std::wstring_view id,
                       std::wstring_view created, std::wstring_view modified) {
    const Byte signature[]{'N', 'V', 'N', static_cast<Byte>(note.folder_id.empty() ? '1' : '2')};
    out.insert(out.end(), std::begin(signature), std::end(signature));
    EncodeField(out, id);
    EncodeField(out, created);
    EncodeField(out, modified);
    EncodeField(out, note.title);
    EncodeField(out, note.text);
    if (!note.folder_id.empty()) EncodeField(out, note.folder_id);
}

inline void EncodeNote(std::vector<Byte>& out, const Note& note) {
    EncodeNote(out, note, note.id, note.created, note.modified);
}

inline bool DecodeNote(const Byte* start, std::size_t length, std::wstring_view id, Note& result,
                       bool keepText = true) {
    if (!start || length < 4 || length > kMaxBlob || start[0] != 'N' || start[1] != 'V' || start[2] != 'N' ||
        (start[3] != '1' && start[3] != '2') || !IsId(id)) return false;
    const Byte* cursor = start + 4;
    const Byte* end = start + length;
    Note note;
    if (!DecodeField(cursor, end, note.id, kIdSize) || note.id != id ||
        !DecodeField(cursor, end, note.created, kDateSize) || !IsDate(note.created) ||
        !DecodeField(cursor, end, note.modified, kDateSize) || !IsDate(note.modified) || note.modified < note.created ||
        !DecodeField(cursor, end, note.title, kMaxTitle) ||
        !DecodeField(cursor, end, note.text, kMaxText, true, keepText)) return false;
    if (start[3] == '2' &&
        (!DecodeField(cursor, end, note.folder_id, kIdSize) || (!note.folder_id.empty() && !IsId(note.folder_id)))) return false;
    if (cursor != end) return false;
    result = std::move(note);
    return true;
}

inline void EncodeFolder(std::vector<Byte>& out, const Folder& folder) {
    const Byte signature[]{'N', 'V', 'F', '1'};
    out.insert(out.end(), std::begin(signature), std::end(signature));
    EncodeField(out, folder.id);
    EncodeField(out, folder.created);
    EncodeField(out, folder.modified);
    EncodeField(out, folder.title);
    EncodeField(out, folder.parent_id);
}

inline bool DecodeFolder(const Byte* start, std::size_t length, std::wstring_view id, Folder& result) {
    if (!start || length < 4 || length > kMaxBlob || start[0] != 'N' || start[1] != 'V' || start[2] != 'F' ||
        start[3] != '1' || !IsId(id)) return false;
    const Byte* cursor = start + 4;
    const Byte* end = start + length;
    Folder folder;
    if (!DecodeField(cursor, end, folder.id, kIdSize) || folder.id != id ||
        !DecodeField(cursor, end, folder.created, kDateSize) || !IsDate(folder.created) ||
        !DecodeField(cursor, end, folder.modified, kDateSize) || !IsDate(folder.modified) || folder.modified < folder.created ||
        !DecodeField(cursor, end, folder.title, kMaxTitle) || !FolderTitle(folder.title) ||
        !DecodeField(cursor, end, folder.parent_id, kIdSize) ||
        (!folder.parent_id.empty() && !IsId(folder.parent_id)) || cursor != end) return false;
    result = std::move(folder);
    return true;
}

} // namespace notes::model
