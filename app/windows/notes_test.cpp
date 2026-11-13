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

} // namespace

int main() {
    try {
        Run();
        std::cout << "Notes smoke test passed.\n";
    } catch (const std::exception& error) {
        std::cerr << "Notes smoke test: " << error.what() << '\n';
        return 1;
    }
}
