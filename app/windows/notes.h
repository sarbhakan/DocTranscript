#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace notes {

inline constexpr std::size_t kMaxTitle = 120;
inline constexpr std::size_t kMaxText = 131072;

struct Note {
    std::wstring id;
    std::wstring title;
    std::wstring text;
    std::wstring created;
    std::wstring modified;
};

class Store {
public:
    // Opens the current Windows user's local library, without creating a note.
    bool Open(std::wstring& error);

    // Returns readable entries (without text), newest first. On a partial
    // failure, out contains the readable entries and error explains the issue.
    bool List(std::vector<Note>& out, std::wstring& error) const;

    // On failure, out is unchanged.
    bool Load(const std::wstring& id, Note& out, std::wstring& error) const;

    // Empty ID creates a note. An existing note requires its last modified
    // value from Load or Save. Updates ID/dates only after committing the file.
    bool Save(Note& inout, std::wstring& error) const;

private:
#ifdef NOTEVIVE_NOTES_TEST
    friend struct StoreTestAccess;
#endif
    std::wstring directory_;
};

} // namespace notes
