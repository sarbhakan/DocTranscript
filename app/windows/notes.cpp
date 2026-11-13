#include "notes.h"

#include <windows.h>
#include <objbase.h>
#include <shlobj.h>
#include <wincrypt.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <utility>

namespace notes {
namespace {

static_assert(sizeof(wchar_t) == 2, "Windows UTF-16 required");
constexpr DWORD kMaxBlob = 1024 * 1024;
constexpr size_t kDateSize = 24;
constexpr size_t kIdSize = 36;
constexpr size_t kHashSize = 32;
constexpr BYTE kSignature[]{'N', 'V', 'N', '1'};
constexpr DWORD kOpenFlags = FILE_FLAG_OPEN_REPARSE_POINT;

struct Handle {
    HANDLE value = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE handle = INVALID_HANDLE_VALUE) : value(handle) {}
    ~Handle() { close(); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    bool valid() const { return value != INVALID_HANDLE_VALUE; }
    void close() {
        if (valid()) CloseHandle(value);
        value = INVALID_HANDLE_VALUE;
    }
};

struct Finder {
    HANDLE value;
    ~Finder() { if (value != INVALID_HANDLE_VALUE) FindClose(value); }
};

struct Blob {
    DATA_BLOB data{};
    ~Blob() {
        if (!data.pbData) return;
        SecureZeroMemory(data.pbData, data.cbData);
        LocalFree(data.pbData);
    }
};

struct Plaintext {
    std::vector<BYTE> bytes;
    ~Plaintext() { if (!bytes.empty()) SecureZeroMemory(bytes.data(), bytes.size()); }
};

struct ComScope {
    HRESULT status = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    ~ComScope() { if (SUCCEEDED(status)) CoUninitialize(); }
    bool ok() const { return SUCCEEDED(status) || status == RPC_E_CHANGED_MODE; }
};

bool Fail(std::wstring& error, const wchar_t* message) {
    error = message;
    return false;
}

bool IsId(const std::wstring& id) {
    if (id.size() != kIdSize) return false;
    for (size_t i = 0; i < id.size(); ++i) {
        const wchar_t ch = id[i];
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (ch != L'-') return false;
        } else if (!((ch >= L'0' && ch <= L'9') || (ch >= L'a' && ch <= L'f'))) {
            return false;
        }
    }
    return true;
}

std::wstring NewId() {
    GUID guid{};
    wchar_t text[39]{};
    if (FAILED(CoCreateGuid(&guid)) || StringFromGUID2(guid, text, 39) != 39) return {};
    std::wstring id(text + 1, kIdSize);
    for (auto& ch : id) if (ch >= L'A' && ch <= L'F') ch += L'a' - L'A';
    return id;
}

bool IsUnicode(const std::wstring& text, bool multiline) {
    for (size_t i = 0; i < text.size(); ++i) {
        const auto ch = static_cast<std::uint16_t>(text[i]);
        if ((ch < 32 && !(multiline && (ch == 9 || ch == 10 || ch == 13))) ||
            (ch >= 0x7f && ch <= 0x9f)) return false;
        if (ch >= 0xd800 && ch <= 0xdbff) {
            if (++i == text.size() || text[i] < 0xdc00 || text[i] > 0xdfff) return false;
        } else if (ch >= 0xdc00 && ch <= 0xdfff) return false;
    }
    return true;
}

std::uint64_t Ticks(const FILETIME& time) {
    return (static_cast<std::uint64_t>(time.dwHighDateTime) << 32) | time.dwLowDateTime;
}

bool ParseDate(const std::wstring& date, std::uint64_t& ticks) {
    if (date.size() != kDateSize || date[4] != L'-' || date[7] != L'-' || date[10] != L'T' ||
        date[13] != L':' || date[16] != L':' || date[19] != L'.' || date[23] != L'Z') return false;
    const auto number = [&](size_t offset, size_t count, WORD& result) {
        result = 0;
        for (size_t i = offset; i < offset + count; ++i) {
            if (date[i] < L'0' || date[i] > L'9') return false;
            result = static_cast<WORD>(result * 10 + date[i] - L'0');
        }
        return true;
    };
    SYSTEMTIME time{};
    FILETIME ft{};
    if (!number(0, 4, time.wYear) || !number(5, 2, time.wMonth) || !number(8, 2, time.wDay) ||
        !number(11, 2, time.wHour) || !number(14, 2, time.wMinute) ||
        !number(17, 2, time.wSecond) || !number(20, 3, time.wMilliseconds) ||
        !SystemTimeToFileTime(&time, &ft)) return false;
    ticks = Ticks(ft);
    return true;
}

std::wstring NowAfter(std::uint64_t previous) {
    FILETIME ft{};
    GetSystemTimeAsFileTime(&ft);
    constexpr std::uint64_t kMillisecond = 10000;
    auto ticks = Ticks(ft) / kMillisecond * kMillisecond;
    if (ticks <= previous) ticks = previous + kMillisecond;
    ft.dwLowDateTime = static_cast<DWORD>(ticks);
    ft.dwHighDateTime = static_cast<DWORD>(ticks >> 32);
    SYSTEMTIME utc{};
    wchar_t formatted[kDateSize + 1]{};
    if (!FileTimeToSystemTime(&ft, &utc) || utc.wYear > 9999 ||
        std::swprintf(formatted, kDateSize + 1, L"%04u-%02u-%02uT%02u:%02u:%02u.%03uZ",
            static_cast<unsigned>(utc.wYear), static_cast<unsigned>(utc.wMonth), static_cast<unsigned>(utc.wDay),
            static_cast<unsigned>(utc.wHour), static_cast<unsigned>(utc.wMinute), static_cast<unsigned>(utc.wSecond),
            static_cast<unsigned>(utc.wMilliseconds)) != static_cast<int>(kDateSize)) return {};
    return formatted;
}

bool PlainFile(HANDLE handle) {
    BY_HANDLE_FILE_INFORMATION info{};
    return GetFileType(handle) == FILE_TYPE_DISK && GetFileInformationByHandle(handle, &info) &&
        !(info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT));
}

bool EnsureDirectory(const std::wstring& directory) {
    if (!CreateDirectoryW(directory.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) return false;
    const DWORD attrs = GetFileAttributesW(directory.c_str());
    return attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY) &&
        !(attrs & FILE_ATTRIBUTE_REPARSE_POINT);
}

std::wstring LocalDirectory(const std::wstring& path) {
    if (path.size() < 3 || path[1] != L':' || path[2] != L'\\') return {};
    Handle root(CreateFileW((L"\\\\?\\" + path).c_str(), FILE_READ_ATTRIBUTES,
                            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                            nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr));
    if (!root.valid()) return {};
    std::wstring finalPath(32768, L'\0');
    const DWORD count = GetFinalPathNameByHandleW(root.value, finalPath.data(),
        static_cast<DWORD>(finalPath.size()), FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    if (count < 7 || count >= finalPath.size()) return {};
    finalPath.resize(count);
    // Check the real volume; a drive-letter path alone may pass through a junction.
    if (finalPath.compare(0, 4, L"\\\\?\\") != 0 || finalPath[5] != L':' || finalPath[6] != L'\\' ||
        GetDriveTypeW(finalPath.substr(4, 3).c_str()) != DRIVE_FIXED) return {};
    if (finalPath.back() == L'\\') finalPath.pop_back();
    return finalPath;
}

std::wstring NotePath(const std::wstring& directory, const std::wstring& id) {
    return directory + L"\\" + id + L".nvn";
}

HANDLE LockWriter(const std::wstring& directory) {
    return CreateFileW((directory + L"\\write.lock").c_str(), GENERIC_READ, 0, nullptr, OPEN_ALWAYS,
                       FILE_ATTRIBUTE_NORMAL | kOpenFlags, nullptr);
}

void DiscardStagingFiles(const std::wstring& directory) {
    Handle lock(LockWriter(directory));
    if (!lock.valid() || !PlainFile(lock.value)) return;
    WIN32_FIND_DATAW info{};
    Finder found{FindFirstFileW((directory + L"\\*.stage").c_str(), &info)};
    if (found.value == INVALID_HANDLE_VALUE) return;
    do {
        const std::wstring name(info.cFileName);
        if (!(info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) &&
            name.size() == kIdSize + 6 && name.compare(kIdSize, 6, L".stage") == 0 &&
            IsId(name.substr(0, kIdSize))) DeleteFileW((directory + L"\\" + name).c_str());
    } while (FindNextFileW(found.value, &info));
}

bool Hash(const BYTE* bytes, size_t size, BYTE* digest) {
    DWORD out = static_cast<DWORD>(kHashSize);
    return CryptHashCertificate2(L"SHA256", 0, nullptr, bytes, static_cast<DWORD>(size), digest, &out) &&
        out == kHashSize;
}

void Encode(std::vector<BYTE>& out, const std::wstring& value) {
    const auto length = static_cast<std::uint32_t>(value.size());
    for (unsigned shift = 0; shift < 32; shift += 8) out.push_back(static_cast<BYTE>(length >> shift));
    if (!value.empty()) {
        const auto* bytes = reinterpret_cast<const BYTE*>(value.data());
        out.insert(out.end(), bytes, bytes + value.size() * sizeof(wchar_t));
    }
}

bool Decode(const BYTE*& cursor, const BYTE* end, std::wstring& value, size_t maxSize) {
    if (end - cursor < 4) return false;
    std::uint32_t length = 0;
    for (unsigned shift = 0; shift < 32; shift += 8) length |= static_cast<std::uint32_t>(*cursor++) << shift;
    if (length > maxSize || static_cast<size_t>(end - cursor) / sizeof(wchar_t) < length) return false;
    value.resize(length);
    if (length) std::memcpy(value.data(), cursor, length * sizeof(wchar_t));
    cursor += length * sizeof(wchar_t);
    return true;
}

bool DecodeNote(const Blob& plain, const std::wstring& id, bool keepText, Note& result) {
    const BYTE* start = plain.data.pbData;
    const size_t size = plain.data.cbData;
    if (!start || size <= sizeof(kSignature) + kHashSize || size > kMaxBlob ||
        std::memcmp(start, kSignature, sizeof(kSignature)) != 0) return false;
    const BYTE* end = start + size - kHashSize;
    std::array<BYTE, kHashSize> digest{};
    if (!Hash(start, static_cast<size_t>(end - start), digest.data()) ||
        std::memcmp(digest.data(), end, kHashSize) != 0) return false;
    const BYTE* cursor = start + sizeof(kSignature);
    std::uint64_t created = 0, modified = 0;
    Note note;
    if (!Decode(cursor, end, note.id, kIdSize) || note.id != id ||
        !Decode(cursor, end, note.created, kDateSize) || !ParseDate(note.created, created) ||
        !Decode(cursor, end, note.modified, kDateSize) || !ParseDate(note.modified, modified) || modified < created ||
        !Decode(cursor, end, note.title, kMaxTitle) || !IsUnicode(note.title, false)) return false;
    const bool textOk = Decode(cursor, end, note.text, kMaxText) && cursor == end && IsUnicode(note.text, true);
    if ((!keepText || !textOk) && !note.text.empty()) {
        SecureZeroMemory(note.text.data(), note.text.size() * sizeof(wchar_t));
        note.text.clear();
    }
    if (!textOk) return false;
    result = std::move(note);
    return true;
}

bool ReadNote(const std::wstring& directory, const std::wstring& id, bool keepText,
              Note& result, std::wstring& error) {
    Handle file(CreateFileW(NotePath(directory, id).c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
                            nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL | kOpenFlags, nullptr));
    LARGE_INTEGER size{};
    if (!file.valid()) return Fail(error, L"Note introuvable ou lecture impossible.");
    if (!PlainFile(file.value) || !GetFileSizeEx(file.value, &size) || size.QuadPart <= 0 || size.QuadPart > kMaxBlob)
        return Fail(error, L"Le fichier de note est invalide.");
    std::vector<BYTE> bytes(static_cast<size_t>(size.QuadPart));
    DWORD read = 0;
    if (!ReadFile(file.value, bytes.data(), static_cast<DWORD>(bytes.size()), &read, nullptr) || read != bytes.size())
        return Fail(error, L"Lecture de la note incomplète.");
    DATA_BLOB encrypted{static_cast<DWORD>(bytes.size()), bytes.data()};
    Blob plain;
    if (!CryptUnprotectData(&encrypted, nullptr, nullptr, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &plain.data) ||
        !DecodeNote(plain, id, keepText, result))
        return Fail(error, L"La note est illisible avec ce compte Windows ou son fichier est endommagé.");
    return true;
}

bool Encrypt(const Note& note, const std::wstring& id, const std::wstring& created,
             const std::wstring& modified, Blob& encrypted) {
    Plaintext plain;
    auto& bytes = plain.bytes;
    bytes.reserve(sizeof(kSignature) + kHashSize + 5 * sizeof(std::uint32_t) +
                  (id.size() + created.size() + modified.size() + note.title.size() + note.text.size()) * sizeof(wchar_t));
    bytes.insert(bytes.end(), kSignature, kSignature + sizeof(kSignature));
    Encode(bytes, id);
    Encode(bytes, created);
    Encode(bytes, modified);
    Encode(bytes, note.title);
    Encode(bytes, note.text);
    const size_t length = bytes.size();
    bytes.resize(length + kHashSize);
    if (!Hash(bytes.data(), length, bytes.data() + length)) return false;
    DATA_BLOB input{static_cast<DWORD>(bytes.size()), bytes.data()};
    return CryptProtectData(&input, L"NoteVive", nullptr, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &encrypted.data) &&
        encrypted.data.cbData && encrypted.data.cbData <= kMaxBlob;
}

bool Commit(const std::wstring& directory, const std::wstring& id, const Blob& encrypted,
            bool replace, std::wstring& error) {
    const auto tempId = NewId();
    if (tempId.empty()) return Fail(error, L"Impossible de préparer l’enregistrement de la note.");
    const auto stage = directory + L"\\" + tempId + L".stage";
    const auto destination = NotePath(directory, id);
    Handle file(CreateFileW(stage.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                            FILE_ATTRIBUTE_NORMAL | kOpenFlags, nullptr));
    if (!file.valid()) return Fail(error, L"Impossible de créer le fichier temporaire chiffré.");
    DWORD written = 0;
    const bool ready = WriteFile(file.value, encrypted.data.pbData, encrypted.data.cbData, &written, nullptr) &&
        written == encrypted.data.cbData && FlushFileBuffers(file.value);
    file.close();
    const DWORD moveFlags = MOVEFILE_WRITE_THROUGH | (replace ? MOVEFILE_REPLACE_EXISTING : 0);
    if (!ready || !MoveFileExW(stage.c_str(), destination.c_str(), moveFlags)) {
        DeleteFileW(stage.c_str());
        return Fail(error, L"Enregistrement interrompu. La note précédente n’a pas été remplacée.");
    }
    return true;
}

} // namespace

bool Store::Open(std::wstring& error) {
    error.clear();
    directory_.clear();
    ComScope com;
    if (!com.ok()) return Fail(error, L"Impossible d’ouvrir la bibliothèque de notes locale.");
    PWSTR path = nullptr;
    const HRESULT status = SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &path);
    const std::wstring local = SUCCEEDED(status) && path ? LocalDirectory(path) : L"";
    CoTaskMemFree(path);
    if (local.empty())
        return Fail(error, L"Le dossier de données du compte Windows doit se trouver sur un disque local.");
    const std::wstring base = local + L"\\NoteVive-Pilote";
    const auto notes = base + L"\\notes";
    if (!EnsureDirectory(base) || !EnsureDirectory(notes))
        return Fail(error, L"Impossible d’ouvrir la bibliothèque de notes locale.");
    directory_ = notes;
    DiscardStagingFiles(directory_);
    return true;
}

bool Store::List(std::vector<Note>& out, std::wstring& error) const {
    error.clear();
    out.clear();
    if (directory_.empty()) return Fail(error, L"La bibliothèque de notes est fermée.");
    WIN32_FIND_DATAW info{};
    Finder found{FindFirstFileW((directory_ + L"\\*.nvn").c_str(), &info)};
    if (found.value == INVALID_HANDLE_VALUE) {
        if (GetLastError() == ERROR_FILE_NOT_FOUND) return true;
        return Fail(error, L"Impossible de lire la bibliothèque de notes.");
    }
    bool complete = true;
    do {
        const std::wstring name(info.cFileName);
        if (name.size() != kIdSize + 4 || name.compare(kIdSize, 4, L".nvn") != 0) continue;
        const auto id = name.substr(0, kIdSize);
        if (!IsId(id)) continue;
        Note note;
        std::wstring detail;
        if (ReadNote(directory_, id, false, note, detail)) out.push_back(std::move(note));
        else complete = false;
    } while (FindNextFileW(found.value, &info));
    if (GetLastError() != ERROR_NO_MORE_FILES) complete = false;
    std::sort(out.begin(), out.end(), [](const Note& a, const Note& b) {
        return a.modified == b.modified ? a.id < b.id : a.modified > b.modified;
    });
    return complete || Fail(error, L"Une partie de la bibliothèque est illisible. Les notes lisibles restent disponibles.");
}

bool Store::Load(const std::wstring& id, Note& out, std::wstring& error) const {
    error.clear();
    if (directory_.empty()) return Fail(error, L"La bibliothèque de notes est fermée.");
    if (!IsId(id)) return Fail(error, L"Identifiant de note invalide.");
    return ReadNote(directory_, id, true, out, error);
}

bool Store::Save(Note& inout, std::wstring& error) const {
    error.clear();
    if (directory_.empty()) return Fail(error, L"La bibliothèque de notes est fermée.");
    if (inout.title.size() > kMaxTitle || inout.text.size() > kMaxText ||
        !IsUnicode(inout.title, false) || !IsUnicode(inout.text, true))
        return Fail(error, L"Le titre ou le texte dépasse la limite ou contient un caractère invalide.");
    const bool create = inout.id.empty();
    auto id = create ? NewId() : inout.id;
    if (!IsId(id)) return Fail(error, L"Identifiant de note invalide.");
    Handle lock(LockWriter(directory_));
    if (!lock.valid() || !PlainFile(lock.value))
        return Fail(error, L"La bibliothèque est momentanément indisponible. Réessayez.");
    std::wstring created;
    std::uint64_t previous = 0;
    if (!create) {
        Note current;
        if (!ReadNote(directory_, id, false, current, error)) return false;
        if (current.modified != inout.modified || !ParseDate(current.modified, previous))
            return Fail(error, L"Cette note a changé depuis son ouverture. Rechargez-la avant de l’enregistrer.");
        created = std::move(current.created);
    }
    auto modified = NowAfter(previous);
    if (modified.empty()) return Fail(error, L"Impossible de dater l’enregistrement.");
    if (create) created = modified;
    Blob encrypted;
    if (!Encrypt(inout, id, created, modified, encrypted))
        return Fail(error, L"Impossible de chiffrer la note avec ce compte Windows.");
    if (!Commit(directory_, id, encrypted, !create, error)) return false;
    inout.id = std::move(id);
    inout.created = std::move(created);
    inout.modified = std::move(modified);
    return true;
}

} // namespace notes
