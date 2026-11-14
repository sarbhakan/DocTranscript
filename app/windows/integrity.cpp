#include "integrity.h"
#include "catalogue_integrity.h"
#ifndef NOTEVIVE_WORKER_BUILD
#include "worker_integrity.h"
#endif
#include <windows.h>
#include <bcrypt.h>
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace doct {
namespace {
struct Expected { const wchar_t* name; std::uint64_t bytes; const char* hex; };
#include "runtime_integrity.h"

constexpr Expected kCatalogue = {L"catalogue.sqlite", NOTEVIVE_CATALOGUE_SIZE, NOTEVIVE_CATALOGUE_SHA256};

struct File {
    HANDLE h = INVALID_HANDLE_VALUE;
    ~File() { if (h != INVALID_HANDLE_VALUE) CloseHandle(h); }
};
struct Algorithm {
    BCRYPT_ALG_HANDLE h = nullptr;
    ~Algorithm() { if (h) BCryptCloseAlgorithmProvider(h, 0); }
};
struct Hash {
    BCRYPT_HASH_HANDLE h = nullptr;
    ~Hash() { if (h) BCryptDestroyHash(h); }
};

bool verify(const std::wstring& dir, const Expected* data, std::size_t count) {
    Algorithm alg;
    if (BCryptOpenAlgorithmProvider(&alg.h, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0) return false;
    DWORD object_size=0, written=0;
    if (BCryptGetProperty(alg.h, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size), &written, 0) < 0
        || written != sizeof(object_size) || !object_size || object_size > 4096) return false;
    std::vector<UCHAR> object(object_size), buffer(256 * 1024);
    for (std::size_t i=0; i<count; ++i) {
        const Expected& expected = data[i];
        const auto path = dir + L"\\" + expected.name;
        File file{CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_FLAG_SEQUENTIAL_SCAN, nullptr)};
        if (file.h == INVALID_HANDLE_VALUE || GetFileType(file.h) != FILE_TYPE_DISK) return false;
        LARGE_INTEGER size{};
        if (!GetFileSizeEx(file.h, &size) || size.QuadPart < 0 || static_cast<std::uint64_t>(size.QuadPart) != expected.bytes)
            return false;
        Hash hash;
        if (BCryptCreateHash(alg.h, &hash.h, object.data(), object_size, nullptr, 0, 0) < 0) return false;
        std::uint64_t seen = 0;
        for (;;) {
            DWORD read = 0;
            if (!ReadFile(file.h, buffer.data(), static_cast<DWORD>(buffer.size()), &read, nullptr)) return false;
            if (!read) break;
            seen += read;
            if (seen > expected.bytes || BCryptHashData(hash.h, buffer.data(), read, 0) < 0) return false;
        }
        std::array<UCHAR, 32> digest{};
        if (seen != expected.bytes || BCryptFinishHash(hash.h, digest.data(), static_cast<ULONG>(digest.size()), 0) < 0)
            return false;
        constexpr char hex[] = "0123456789abcdef";
        for (std::size_t j=0; j<digest.size(); ++j) {
            if (expected.hex[j*2] != hex[digest[j] >> 4] || expected.hex[j*2+1] != hex[digest[j] & 15]) return false;
        }
    }
    return true;
}
}

bool verify_engine_files(const std::wstring& dir) noexcept {
    try { return verify(dir, kEngine, std::size(kEngine)); } catch (...) { return false; }
}
bool verify_worker_file(const std::wstring& dir) noexcept {
#ifdef NOTEVIVE_WORKER_BUILD
    (void)dir;
    return false;
#else
    constexpr Expected worker{L"NoteVive-ASR.exe", NOTEVIVE_WORKER_SIZE, NOTEVIVE_WORKER_SHA256};
    try { return verify(dir, &worker, 1); } catch (...) { return false; }
#endif
}
bool verify_catalogue_file(const std::wstring& dir) noexcept {
    try { return verify(dir, &kCatalogue, 1); } catch (...) { return false; }
}
}
