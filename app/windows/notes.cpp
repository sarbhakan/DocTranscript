#include "notes.h"
#include "notes_model.h"

#include <windows.h>
#include <objbase.h>
#include <shlobj.h>
#include <wincrypt.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <unordered_set>
#include <utility>

namespace notes {
namespace {

static_assert(sizeof(wchar_t) == 2, "Windows UTF-16 required");
using model::kMaxBlob;
using model::kDateSize;
using model::kIdSize;
using model::IsId;
constexpr size_t kHashSize = 32;
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

std::wstring NewId() {
    GUID guid{};
    wchar_t text[39]{};
    if (FAILED(CoCreateGuid(&guid)) || StringFromGUID2(guid, text, 39) != 39) return {};
    std::wstring id(text + 1, kIdSize);
    for (auto& ch : id) if (ch >= L'A' && ch <= L'F') ch += L'a' - L'A';
    return id;
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

std::wstring RecordPath(const std::wstring& directory, std::wstring_view id, std::wstring_view suffix) {
    std::wstring result = directory + L"\\";
    result.append(id);
    result.append(suffix);
    return result;
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

bool ReadRecord(const std::wstring& path, Blob& plain, std::wstring& error) {
    Handle file(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
                            nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL | kOpenFlags, nullptr));
    LARGE_INTEGER size{};
    if (!file.valid()) return Fail(error, L"Élément introuvable ou lecture impossible.");
    if (!PlainFile(file.value) || !GetFileSizeEx(file.value, &size) || size.QuadPart <= 0 ||
        static_cast<std::uint64_t>(size.QuadPart) > kMaxBlob)
        return Fail(error, L"Le fichier de bibliothèque est invalide.");
    std::vector<BYTE> bytes(static_cast<size_t>(size.QuadPart));
    DWORD read = 0;
    if (!ReadFile(file.value, bytes.data(), static_cast<DWORD>(bytes.size()), &read, nullptr) || read != bytes.size())
        return Fail(error, L"Lecture de la bibliothèque incomplète.");
    DATA_BLOB encrypted{static_cast<DWORD>(bytes.size()), bytes.data()};
    if (!CryptUnprotectData(&encrypted, nullptr, nullptr, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &plain.data) ||
        !plain.data.pbData || plain.data.cbData <= kHashSize || plain.data.cbData > kMaxBlob)
        return Fail(error, L"Élément illisible avec ce compte Windows ou fichier endommagé.");
    std::array<BYTE, kHashSize> digest{};
    const auto sizeWithoutHash = plain.data.cbData - kHashSize;
    if (!Hash(plain.data.pbData, sizeWithoutHash, digest.data()) ||
        std::memcmp(digest.data(), plain.data.pbData + sizeWithoutHash, kHashSize) != 0)
        return Fail(error, L"Élément illisible avec ce compte Windows ou fichier endommagé.");
    return true;
}

bool ReadNote(const std::wstring& directory, const std::wstring& id, bool keepText,
              Note& result, std::wstring& error) {
    Blob plain;
    if (!ReadRecord(RecordPath(directory, id, L".nvn"), plain, error)) return false;
    return model::DecodeNote(plain.data.pbData, plain.data.cbData - kHashSize, id, result, keepText) ||
        Fail(error, L"La note est endommagée ou sa version est incompatible.");
}

bool ReadFolder(const std::wstring& directory, const std::wstring& id, Folder& result, std::wstring& error) {
    Blob plain;
    if (!ReadRecord(RecordPath(directory, id, L".nvf"), plain, error)) return false;
    return model::DecodeFolder(plain.data.pbData, plain.data.cbData - kHashSize, id, result) ||
        Fail(error, L"Le dossier est endommagé ou sa version est incompatible.");
}

bool Encrypt(Plaintext& plain, Blob& encrypted) {
    auto& bytes = plain.bytes;
    const size_t length = bytes.size();
    if (length > kMaxBlob - kHashSize) return false;
    bytes.resize(length + kHashSize);
    if (!Hash(bytes.data(), length, bytes.data() + length)) return false;
    DATA_BLOB input{static_cast<DWORD>(bytes.size()), bytes.data()};
    return CryptProtectData(&input, L"NoteVive", nullptr, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &encrypted.data) &&
        encrypted.data.cbData && encrypted.data.cbData <= kMaxBlob;
}

bool Commit(const std::wstring& directory, const std::wstring& destination, const Blob& encrypted,
            bool replace, std::wstring& error) {
    const auto tempId = NewId();
    if (tempId.empty()) return Fail(error, L"Impossible de préparer l’enregistrement.");
    const auto stage = directory + L"\\" + tempId + L".stage";
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
        return Fail(error, L"Enregistrement interrompu. Le fichier précédent n’a pas été remplacé.");
    }
    return true;
}

template <typename Visitor>
bool VisitRecords(const std::wstring& directory, const std::wstring& suffix, Visitor visit) {
    WIN32_FIND_DATAW info{};
    Finder found{FindFirstFileW((directory + L"\\*" + suffix).c_str(), &info)};
    if (found.value == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_FILE_NOT_FOUND;
    bool complete = true;
    do {
        const std::wstring filename(info.cFileName);
        if (filename.size() != kIdSize + suffix.size() || filename.compare(kIdSize, suffix.size(), suffix) != 0)
            continue;
        const auto id = filename.substr(0, kIdSize);
        if (IsId(id) && !visit(id)) complete = false;
    } while (FindNextFileW(found.value, &info));
    return GetLastError() == ERROR_NO_MORE_FILES && complete;
}

bool ReadFolders(const std::wstring& directory, std::vector<Folder>& folders) {
    std::size_t attempted = 0;
    return VisitRecords(directory, L".nvf", [&](const std::wstring& id) {
        // Cap the runtime view and the number of decryptions even if the
        // folder has been populated by a different version or process.
        if (attempted == kMaxFolders) return false;
        ++attempted;
        Folder folder;
        std::wstring detail;
        if (!ReadFolder(directory, id, folder, detail)) return false;
        folders.push_back(std::move(folder));
        return true;
    });
}

bool SameFolderTitle(std::wstring_view normalized, std::wstring_view title) {
    const auto other = model::Fold(title);
    if (normalized == other) return true;
    if (normalized.empty() || other.empty()) return false;
    return CompareStringEx(L"fr-FR", NORM_IGNORECASE | NORM_IGNORENONSPACE,
        normalized.data(), static_cast<int>(normalized.size()),
        other.data(), static_cast<int>(other.size()), nullptr, nullptr, 0) == CSTR_EQUAL;
}

enum class FolderAccess { Available, InvalidChain, Unreadable };

FolderAccess CheckFolderAccess(const std::wstring& directory, std::wstring folderId) {
    std::unordered_set<std::wstring> ancestry;
    std::wstring detail;
    while (!folderId.empty()) {
        if (ancestry.size() == kMaxFolderDepth || !ancestry.insert(folderId).second)
            return FolderAccess::InvalidChain;
        Folder folder;
        if (!ReadFolder(directory, folderId, folder, detail)) return FolderAccess::Unreadable;
        folderId = std::move(folder.parent_id);
    }
    return FolderAccess::Available;
}

} // namespace

std::wstring FolderPath(const std::vector<Folder>& folders, const std::wstring& id) {
    return model::ViewPath(folders, id);
}

bool Matches(const Query& query, const Note& note, const std::vector<Folder>& folders) {
    return (!query.filter_folder || model::MatchFolder(query, note, model::FolderIndex(folders))) &&
        model::MatchText(model::Fold(query.text), note);
}

void SortNotes(std::vector<Note>& notes, Sort sort) {
    model::OrderNotes(notes, sort);
}

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
    return List(Query{}, out, error);
}

bool Store::List(const Query& query, std::vector<Note>& out, std::wstring& error) const {
    error.clear();
    out.clear();
    if (directory_.empty()) return Fail(error, L"La bibliothèque de notes est fermée.");
    if (query.filter_folder && !query.folder_id.empty() && !IsId(query.folder_id))
        return Fail(error, L"Identifiant de dossier invalide.");
    const auto needle = model::Fold(query.text);
    std::vector<Folder> folders;
    std::wstring foldersError;
    const bool complete = !query.filter_folder || (query.folder_id.empty() && query.include_descendants) ||
        ListFolders(folders, foldersError);
    const model::FolderIndex index(folders);
    const bool notesComplete = VisitRecords(directory_, L".nvn", [&](const std::wstring& id) {
        Note note;
        std::wstring detail;
        if (!ReadNote(directory_, id, !needle.empty(), note, detail)) return false;
        const bool include = model::MatchFolder(query, note, index) && model::MatchText(needle, note);
        if (!note.text.empty()) {
            SecureZeroMemory(note.text.data(), note.text.size() * sizeof(wchar_t));
            note.text.clear();
        }
        if (include) out.push_back(std::move(note));
        return true;
    });
    model::OrderNotes(out, query.sort);
    if (!notesComplete) return Fail(error, L"Une partie de la bibliothèque est illisible. Les notes lisibles restent disponibles.");
    if (!complete) error = std::move(foldersError);
    return complete;
}

bool Store::ListFolders(std::vector<Folder>& out, std::wstring& error) const {
    error.clear();
    out.clear();
    if (directory_.empty()) return Fail(error, L"La bibliothèque de notes est fermée.");
    const bool read = ReadFolders(directory_, out);
    const bool valid = model::RepairFolderView(out);
    std::sort(out.begin(), out.end(), [](const Folder& a, const Folder& b) {
        const auto ta = model::Fold(a.title), tb = model::Fold(b.title);
        return ta == tb ? a.id < b.id : ta < tb;
    });
    return (read && valid) || Fail(error, L"Une partie des dossiers est illisible ou mal rattachée. Les éléments lisibles restent disponibles.");
}

bool Store::Load(const std::wstring& id, Note& out, std::wstring& error) const {
    error.clear();
    if (directory_.empty()) return Fail(error, L"La bibliothèque de notes est fermée.");
    if (!IsId(id)) return Fail(error, L"Identifiant de note invalide.");
    return ReadNote(directory_, id, true, out, error);
}

bool Store::Save(Note& inout, std::wstring& error) const {
    return SaveNote(inout, error, false);
}

bool Store::SaveRecoveryCopy(Note& inout, std::wstring& error) const {
    if (!IsId(inout.id)) return Fail(error, L"Il n’y a pas de note existante à copier.");
    return SaveNote(inout, error, true);
}

bool Store::SaveNote(Note& inout, std::wstring& error, bool recoveryCopy) const {
    error.clear();
    if (directory_.empty()) return Fail(error, L"La bibliothèque de notes est fermée.");
    if (inout.title.size() > kMaxTitle || inout.text.size() > kMaxText ||
        !model::IsUnicode(inout.title, false) || !model::IsUnicode(inout.text, true))
        return Fail(error, L"Le titre ou le texte dépasse la limite ou contient un caractère invalide.");
    if (!inout.folder_id.empty() && !IsId(inout.folder_id)) return Fail(error, L"Identifiant de dossier invalide.");
    const bool create = recoveryCopy || inout.id.empty();
    auto id = create ? NewId() : inout.id;
    if (!IsId(id)) return Fail(error, L"Identifiant de note invalide.");
    Handle lock(LockWriter(directory_));
    if (!lock.valid() || !PlainFile(lock.value))
        return Fail(error, L"La bibliothèque est momentanément indisponible. Réessayez.");
    Note current;
    std::uint64_t previous = 0;
    if (!create) {
        if (!ReadNote(directory_, id, false, current, error)) return false;
        if (current.modified != inout.modified || !ParseDate(current.modified, previous))
            return Fail(error, L"Cette note a changé. Ctrl+S permet de sauvegarder une copie du brouillon.");
    }
    auto folderId = inout.folder_id;
    if (!folderId.empty() && folderId != current.folder_id) {
        // Read only the ancestry of the destination, not every folder. A
        // missing folder cannot attach a new/moved note, but a note already
        // in a damaged folder stays editable and can be moved back to root.
        const auto access = CheckFolderAccess(directory_, folderId);
        if (access != FolderAccess::Available) {
            if (recoveryCopy) folderId.clear();
            else return Fail(error, access == FolderAccess::InvalidChain ? L"Le rattachement du dossier est invalide."
                                                                         : L"Le dossier de destination est inaccessible.");
        }
    }
    auto modified = NowAfter(previous);
    if (modified.empty()) return Fail(error, L"Impossible de dater l’enregistrement.");
    auto created = create ? modified : std::move(current.created);
    Plaintext plain;
    plain.bytes.reserve(4 + kHashSize + 6 * sizeof(std::uint32_t) +
        (id.size() + created.size() + modified.size() + inout.title.size() + inout.text.size() + folderId.size()) * 2);
    model::EncodeNote(plain.bytes, inout, id, created, modified, folderId);
    Blob encrypted;
    if (!Encrypt(plain, encrypted))
        return Fail(error, L"Impossible de chiffrer la note avec ce compte Windows.");
    if (!Commit(directory_, RecordPath(directory_, id, L".nvn"), encrypted, !create, error)) return false;
    inout.id = std::move(id);
    inout.created = std::move(created);
    inout.modified = std::move(modified);
    inout.folder_id = std::move(folderId);
    return true;
}

bool Store::SaveFolder(Folder& inout, std::wstring& error) const {
    error.clear();
    if (directory_.empty()) return Fail(error, L"La bibliothèque de notes est fermée.");
    if (!model::FolderTitle(inout.title))
        return Fail(error, L"Choisissez un nom de dossier valide (120 caractères maximum).");
    if (!inout.parent_id.empty() && !IsId(inout.parent_id))
        return Fail(error, L"Identifiant de dossier parent invalide.");
    const bool create = inout.id.empty();
    auto id = create ? NewId() : inout.id;
    if (!IsId(id)) return Fail(error, L"Identifiant de dossier invalide.");
    Handle lock(LockWriter(directory_));
    if (!lock.valid() || !PlainFile(lock.value))
        return Fail(error, L"La bibliothèque est momentanément indisponible. Réessayez.");

    Folder current;
    std::uint64_t previous = 0;
    if (!create) {
        if (!ReadFolder(directory_, id, current, error)) return false;
        if (current.modified != inout.modified || !ParseDate(current.modified, previous))
            return Fail(error, L"Ce dossier a changé depuis son ouverture. Rechargez-le avant de l’enregistrer.");
    }
    Folder pending{id, inout.title, inout.parent_id, {}, {}};
    const bool move = create || current.parent_id != pending.parent_id;
    if (move || current.title != pending.title) {
        const auto normalizedTitle = model::Fold(pending.title);
        if (!model::NewFolderTitle(pending.title) || normalizedTitle.empty())
            return Fail(error, L"Choisissez un nom de dossier sans / ni \\.");
        if (pending.parent_id.empty() && (SameFolderTitle(normalizedTitle, L"Sans dossier") ||
                SameFolderTitle(normalizedTitle, L"À la racine")))
            return Fail(error, L"Ce nom est réservé à la racine. Choisissez un autre nom de dossier.");
        std::vector<Folder> folders;
        // Read sibling names while holding the same writer lock as the commit.
        // An unreadable sidecar could hide a sibling or affect a move's depth.
        const bool complete = ReadFolders(directory_, folders);
        if (create && folders.size() >= kMaxFolders)
            return Fail(error, L"La bibliothèque a atteint sa limite de dossiers.");
        if (!complete)
            return Fail(error, L"Organisation des dossiers impossible tant que certains dossiers sont illisibles.");
        if (std::any_of(folders.begin(), folders.end(), [&](const auto& sibling) {
                return sibling.id != pending.id && sibling.parent_id == pending.parent_id &&
                    SameFolderTitle(normalizedTitle, sibling.title);
            })) return Fail(error, L"Un dossier portant ce nom existe déjà à cet emplacement.");
        if (move) {
            switch (model::CheckFolderMove(pending, folders)) {
            case model::MoveResult::Ok: break;
            case model::MoveResult::MissingParent:
                return Fail(error, L"Le dossier parent est introuvable ou mal rattaché.");
            case model::MoveResult::Cycle:
                return Fail(error, L"Un dossier ne peut pas être placé dans lui-même ou dans un de ses sous-dossiers.");
            case model::MoveResult::TooDeep:
                return Fail(error, L"Cette action dépasserait 32 niveaux de dossiers.");
            }
        }
    }
    pending.modified = NowAfter(previous);
    if (pending.modified.empty()) return Fail(error, L"Impossible de dater l’enregistrement.");
    pending.created = create ? pending.modified : std::move(current.created);
    Plaintext plain;
    plain.bytes.reserve(4 + kHashSize + 5 * sizeof(std::uint32_t) +
        (pending.id.size() + pending.created.size() + pending.modified.size() + pending.title.size() + pending.parent_id.size()) * 2);
    model::EncodeFolder(plain.bytes, pending);
    Blob encrypted;
    if (!Encrypt(plain, encrypted))
        return Fail(error, L"Impossible de chiffrer le dossier avec ce compte Windows.");
    if (!Commit(directory_, RecordPath(directory_, id, L".nvf"), encrypted, !create, error)) return false;
    inout = std::move(pending);
    return true;
}

} // namespace notes
