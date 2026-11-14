#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace notes {

inline constexpr std::size_t kMaxTitle = 120;
inline constexpr std::size_t kMaxText = 131072;
inline constexpr std::size_t kMaxFolders = 1000;
inline constexpr std::size_t kMaxFolderDepth = 32;

struct Note {
    std::wstring id;
    std::wstring title;
    std::wstring text;
    std::wstring created;
    std::wstring modified;
    std::wstring folder_id;
};

struct Folder {
    std::wstring id;
    std::wstring title;
    std::wstring parent_id;
    std::wstring created;
    std::wstring modified;
};

enum class Sort { ModifiedNewest, CreatedNewest, TitleAscending };

struct Query {
    std::wstring text;
    std::wstring folder_id;
    bool filter_folder = false;
    bool include_descendants = false;
    Sort sort = Sort::ModifiedNewest;
};

// Display path. An empty result means the root or a missing/invalid folder.
std::wstring FolderPath(const std::vector<Folder>& folders, const std::wstring& id);
bool Matches(const Query& query, const Note& note, const std::vector<Folder>& folders);
void SortNotes(std::vector<Note>& notes, Sort sort);

class Store {
public:
    // Opens the current Windows user's local library, without creating a note.
    bool Open(std::wstring& error);

    // Returns readable entries (without text), newest first. On a partial
    // failure, out contains the readable entries and error explains the issue.
    bool List(std::vector<Note>& out, std::wstring& error) const;

    // Filters by folder and/or searches title and body. Results omit text.
    bool List(const Query& query, std::vector<Note>& out, std::wstring& error) const;
    bool ListFolders(std::vector<Folder>& out, std::wstring& error) const;

    // On failure, out is unchanged.
    bool Load(const std::wstring& id, Note& out, std::wstring& error) const;

    // Empty ID creates a note. An existing note requires its last modified
    // value from Load or Save. Updates ID/dates only after committing the file.
    bool Save(Note& inout, std::wstring& error) const;

    // Save the editor as a new note; retain its folder only if still accessible.
    // The original file is never replaced. On failure, inout is unchanged.
    bool SaveRecoveryCopy(Note& inout, std::wstring& error) const;

    // Empty ID creates a folder. Rename/move requires the latest revision.
    // An empty parent_id represents the top level.
    bool SaveFolder(Folder& inout, std::wstring& error) const;

private:
#ifdef NOTEVIVE_NOTES_TEST
    friend struct StoreTestAccess;
#endif
    bool SaveNote(Note& inout, std::wstring& error, bool recoveryCopy) const;
    std::wstring directory_;
};

} // namespace notes
