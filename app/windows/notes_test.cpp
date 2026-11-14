#include "notes.h"

#include <windows.h>
#include <objbase.h>

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <utility>

#ifndef NOTEVIVE_NOTES_TEST
#error Build both notes.cpp and notes_test.cpp with NOTEVIVE_NOTES_TEST.
#endif

namespace notes {
struct StoreTestAccess {
    static void SetDirectory(Store& store, std::wstring path) { store.directory_ = std::move(path); }
};
} // namespace notes

namespace {

void Check(bool good, const char* message) {
    if (!good) throw std::runtime_error(message);
}

struct TestDirectory {
    std::filesystem::path path;
    TestDirectory() {
        GUID id{};
        wchar_t name[39]{};
        wchar_t temp[32768]{};
        const DWORD chars = GetTempPathW(static_cast<DWORD>(std::size(temp)), temp);
        Check(chars && chars < std::size(temp), "temporary path");
        Check(SUCCEEDED(CoCreateGuid(&id)) && StringFromGUID2(id, name, 39) == 39, "test ID");
        path = std::filesystem::path(temp) / (std::wstring(L"NoteVive-notes-test-") + name);
        Check(std::filesystem::create_directory(path), "isolated test folder");
    }
    ~TestDirectory() {
        std::error_code error;
        std::filesystem::remove_all(path, error);
    }
};

std::vector<char> ReadBytes(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    Check(static_cast<bool>(input), "read fixture bytes");
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

bool Contains(const std::vector<char>& haystack, const char* start, size_t size) {
    return std::search(haystack.begin(), haystack.end(), start, start + size) != haystack.end();
}

void Run() {
    TestDirectory temp;
    notes::Store library, concurrent;
    notes::StoreTestAccess::SetDirectory(library, temp.path.wstring());
    notes::StoreTestAccess::SetDirectory(concurrent, temp.path.wstring());
    std::wstring error;
    std::vector<notes::Note> entries;
    Check(library.List(entries, error) && entries.empty(), "empty library");

    notes::Note note;
    note.title = L"Titre fictif : œdème";
    note.text = L"NOTE-FICTIVE-TEST-3fbb1a29\r\nDeuxième ligne \U0001F4DD";
    Check(library.Save(note, error) && note.id.size() == 36 && !note.created.empty() &&
          note.created == note.modified, "initial save");
    const auto path = temp.path / (note.id + L".nvn");
    const auto firstBytes = ReadBytes(path);
    const std::string sentinel = "NOTE-FICTIVE-TEST-3fbb1a29";
    Check(!firstBytes.empty() && !Contains(firstBytes, sentinel.data(), sentinel.size()) &&
          !Contains(firstBytes, reinterpret_cast<const char*>(note.text.data()), note.text.size() * sizeof(wchar_t)) &&
          !Contains(firstBytes, reinterpret_cast<const char*>(note.title.data()), note.title.size() * sizeof(wchar_t)),
          "cleartext not stored");
    notes::Note stale;
    Check(concurrent.Load(note.id, stale, error) && stale.title == note.title && stale.text == note.text &&
          stale.modified == note.modified, "UTF-16 round trip");
    Check(library.List(entries, error) && entries.size() == 1 && entries[0].title == note.title &&
          entries[0].text.empty(), "metadata only");
    const auto originalDate = note.created;
    note.title += L" relu";
    Check(library.Save(note, error) && note.created == originalDate && note.modified > stale.modified,
          "replace note and preserve creation date");
    const auto updatedBytes = ReadBytes(path);
    Check(!concurrent.Save(stale, error) && !error.empty() && ReadBytes(path) == updatedBytes,
          "reject outdated update");

    const HANDLE locked = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    Check(locked != INVALID_HANDLE_VALUE, "lock destination for interruption test");
    note.text += L" brouillon";
    const auto lastSavedDate = note.modified;
    const bool savedWithLock = library.Save(note, error);
    CloseHandle(locked);
    Check(!savedWithLock && !error.empty() && note.modified == lastSavedDate && ReadBytes(path) == updatedBytes,
          "commit failure preserves prior file and note revision");
    for (const auto& entry : std::filesystem::directory_iterator(temp.path))
        Check(entry.path().extension() != L".stage", "failed stage removed");
    Check(library.Save(note, error) && note.modified > lastSavedDate, "successful retry");

    notes::Folder top;
    top.title = L"Cardiologie fictive";
    Check(library.SaveFolder(top, error) && top.id.size() == 36 && top.created == top.modified,
          "save encrypted top-level folder");
    notes::Folder child;
    child.title = L"Consultations fictives";
    child.parent_id = top.id;
    Check(library.SaveFolder(child, error), "save nested folder");
    const auto folderFile = temp.path / (child.id + L".nvf");
    const auto folderBytes = ReadBytes(folderFile);
    Check(!Contains(folderBytes, reinterpret_cast<const char*>(child.title.data()), child.title.size() * sizeof(wchar_t)),
          "folder title not stored in cleartext");
    notes::Folder cycle = top;
    cycle.parent_id = child.id;
    Check(!library.SaveFolder(cycle, error), "prevent folder cycle");
    const auto beforeMove = note.modified;
    note.folder_id = child.id;
    Check(library.Save(note, error) && note.created == originalDate && note.modified > beforeMove,
          "moving legacy note preserves creation date");

    notes::Store reopened;
    notes::StoreTestAccess::SetDirectory(reopened, temp.path.wstring());
    std::vector<notes::Folder> folders;
    Check(reopened.ListFolders(folders, error) && folders.size() == 2 &&
          notes::FolderPath(folders, child.id) == L"Cardiologie fictive / Consultations fictives",
          "reopen folder hierarchy");
    notes::Note moved;
    Check(reopened.Load(note.id, moved, error) && moved.text == note.text && moved.folder_id == child.id,
          "reopen file with folder and original text");
    notes::Query query{L"DEUXIEME ligne", top.id, true, true, notes::Sort::CreatedNewest};
    Check(reopened.List(query, entries, error) && entries.size() == 1 && entries[0].id == note.id &&
          entries[0].text.empty(), "accent-insensitive body search in descendants without returning text");
    query.include_descendants = false;
    Check(reopened.List(query, entries, error) && entries.empty(), "direct folder excludes descendants");
    auto oldFolder = child;
    child.title += L" relues";
    child.parent_id.clear();
    const auto folderCreation = child.created;
    Check(reopened.SaveFolder(child, error) && child.modified > oldFolder.modified && child.created == folderCreation,
          "rename and move folder preserve creation date");
    Check(!library.SaveFolder(oldFolder, error), "reject stale folder revision");
    {
        std::ofstream corrupt(folderFile, std::ios::binary | std::ios::trunc);
        Check(static_cast<bool>(corrupt), "open isolated corrupt folder fixture");
        corrupt << "not DPAPI";
    }
    Check(!reopened.ListFolders(folders, error) && folders.size() == 1 && folders[0].id == top.id,
          "corrupt folder leaves other folders readable");
    Check(library.Load(note.id, moved, error) && moved.folder_id == child.id && moved.text == note.text,
          "orphan note still readable with original folder reference");
    query = {};
    query.filter_folder = true;
    Check(!reopened.List(query, entries, error) && entries.size() == 1 && entries[0].id == note.id,
          "orphan note is visible when browsing unfiled");
    moved.folder_id.clear();
    Check(library.Save(moved, error) && moved.created == originalDate,
          "orphan note can safely be moved to unfiled");
    note = std::move(moved);

    notes::Note untouched;
    untouched.title = L"sentinelle";
    Check(!library.Load(L"..\\outside", untouched, error) && untouched.title == L"sentinelle", "reject invalid ID");
    const std::wstring secondId = L"76543210-aaaa-bbbb-cccc-987654321012";
    Check(std::filesystem::copy_file(path, temp.path / (secondId + L".nvn")), "clone as invalid second ID");
    Check(!library.Load(secondId, untouched, error) && untouched.title == L"sentinelle", "reject mismatched note ID");
    Check(!library.List(entries, error) && entries.size() == 1 && entries[0].id == note.id, "partial library error");
    {
        std::ofstream corrupt(path, std::ios::binary | std::ios::trunc);
        Check(static_cast<bool>(corrupt), "truncate note fixture");
        corrupt << "not DPAPI";
    }
    Check(!library.Load(note.id, untouched, error) && untouched.title == L"sentinelle", "reject corrupt file");
    Check(!library.Save(note, error), "cannot replace a corrupt note with an old copy");
}

void ConflictsAndRecovery() {
    TestDirectory temp;
    notes::Store first, second;
    notes::StoreTestAccess::SetDirectory(first, temp.path.wstring());
    notes::StoreTestAccess::SetDirectory(second, temp.path.wstring());
    std::wstring error;
    notes::Folder top;
    top.title = L"Équipe médicale";
    Check(first.SaveFolder(top, error), "create fixture folder");
    const auto topPath = temp.path / (top.id + L".nvf");
    const auto topBytes = ReadBytes(topPath);
    notes::Folder same;
    same.title = L" \u00a0E\u0301QUIPE  MeDICALE\u202f";
    Check(!second.SaveFolder(same, error) && same.id.empty() && error.find(L"existe déjà") != error.npos &&
          ReadBytes(topPath) == topBytes, "duplicate normalized sibling name protected under writer lock");
    same.parent_id = top.id;
    Check(first.SaveFolder(same, error), "same name remains usable under a different parent");
    auto moved = same;
    moved.parent_id.clear();
    const auto childPath = temp.path / (same.id + L".nvf");
    const auto childBytes = ReadBytes(childPath);
    Check(!second.SaveFolder(moved, error) && error.find(L"existe déjà") != error.npos &&
          ReadBytes(childPath) == childBytes && ReadBytes(topPath) == topBytes, "moving cannot duplicate a sibling");
    notes::Folder other;
    other.title = L"Dossier distinct";
    Check(second.SaveFolder(other, error), "create distinct fixture folder");
    const auto otherPath = temp.path / (other.id + L".nvf");
    const auto otherBytes = ReadBytes(otherPath);
    other.title = L"équipe médicale";
    Check(!first.SaveFolder(other, error) && error.find(L"existe déjà") != error.npos &&
          ReadBytes(otherPath) == otherBytes, "rename cannot duplicate a sibling");
    notes::Folder ambiguous;
    ambiguous.title = L"Imitation / sous-dossier";
    Check(!first.SaveFolder(ambiguous, error) && ambiguous.id.empty(), "new folder cannot impersonate a breadcrumb");
    ambiguous.title = L"SANS  DOSSIER";
    Check(!first.SaveFolder(ambiguous, error) && ambiguous.id.empty(), "root cannot impersonate the unfiled destination");

    notes::Note original;
    original.title = L"Note fictive";
    original.text = L"Version initiale.";
    original.folder_id = same.id;
    Check(first.Save(original, error), "save note in nested folder");
    auto stale = original;
    original.text = L"Version sauvegardée dans l’autre fenêtre.";
    Check(first.Save(original, error), "advance saved revision");
    const auto notePath = temp.path / (original.id + L".nvn");
    const auto savedBytes = ReadBytes(notePath);
    stale.text = L"Texte du brouillon, à conserver.";
    Check(!second.Save(stale, error) && error.find(L"Ctrl+S") != error.npos, "stale revision explains copy action");
    const auto lockPath = temp.path / L"write.lock";
    const HANDLE writer = CreateFileW(lockPath.c_str(), GENERIC_READ, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    Check(writer != INVALID_HANDLE_VALUE, "hold fixture writer lock");
    auto blockedCopy = stale;
    const bool savedWithWriterLock = second.SaveRecoveryCopy(blockedCopy, error);
    CloseHandle(writer);
    Check(!savedWithWriterLock && blockedCopy.id == stale.id && blockedCopy.text == stale.text &&
          blockedCopy.modified == stale.modified && blockedCopy.folder_id == stale.folder_id && ReadBytes(notePath) == savedBytes,
          "a recovery write failure does not mutate the current draft or original file");
    auto filedCopy = stale;
    Check(second.SaveRecoveryCopy(filedCopy, error) && filedCopy.id != original.id && !filedCopy.id.empty() &&
          filedCopy.created == filedCopy.modified && filedCopy.folder_id == same.id && ReadBytes(notePath) == savedBytes,
          "recovery creates a fresh encrypted note and keeps its accessible folder");
    Check(std::filesystem::remove(topPath), "remove parent of still-readable child folder");
    auto rootCopy = stale;
    Check(second.SaveRecoveryCopy(rootCopy, error) && !rootCopy.id.empty() && rootCopy.id != filedCopy.id &&
          rootCopy.id != original.id && rootCopy.folder_id.empty() && rootCopy.created == rootCopy.modified &&
          ReadBytes(notePath) == savedBytes, "unreadable ancestry recovers to a new unfiled note without touching the original");
    notes::Note reread;
    Check(first.Load(filedCopy.id, reread, error) && reread.text == stale.text && reread.folder_id == same.id,
          "filed copy retains full draft and original association");
    Check(first.Load(rootCopy.id, reread, error) && reread.text == stale.text && reread.title == stale.title &&
          reread.folder_id.empty(), "unfiled copy survives reopen with full draft");
    Check(first.Load(original.id, reread, error) && reread.text == original.text && reread.modified == original.modified &&
          reread.folder_id == same.id, "unchanged original remains readable with its prior folder and revision");
}

} // namespace

int main() {
    try {
        Run();
        ConflictsAndRecovery();
        std::cout << "Notes smoke test passed.\n";
    } catch (const std::exception& error) {
        std::cerr << "Notes smoke test: " << error.what() << '\n';
        return 1;
    }
}
