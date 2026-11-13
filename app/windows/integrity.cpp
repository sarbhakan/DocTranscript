#include "integrity.h"
#include <windows.h>
#include <bcrypt.h>
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace doct {
namespace {
struct Expected { const wchar_t* name; std::uint64_t bytes; const char* hex; };
constexpr Expected kEngine[] = {
    {L"encoder.onnx", 126655903, "47a94a7fdc8dff63d708be4ea0535747640224467f91e238311f1ddbdd09327e"},
    {L"decoder.onnx", 2092272, "3ef2840b684440e26382af87b2174d25732a9f113f1965cd8abba7ffc5d033fb"},
    {L"joiner.onnx", 259572, "fc2f3bb851a15a532c6f2422d53eecd1ca949f12b0897e07a852021c30481711"},
    {L"tokens.txt", 4819, "37fb3f2a7bcb85e5fff3f1f66be04e6fbb05077a22f56d177fe85704e945fb31"},
    {L"sherpa-onnx-c-api.dll", 3667968, "ee2af9f49b8fc5dae135ad20c0b955cbab90d17b79cc1ad0db91e03b24962f68"},
    {L"onnxruntime.dll", 17799168, "7f66f939a881baf4f46a2216496798edf4a1429878b646d12674aa62f27d8a25"},
    {L"onnxruntime_providers_shared.dll", 104960, "551d0e1fe4c227d8542314ba718d52f4379e0c7bfe729a37c59833a884e27b4d"},
};
constexpr Expected kCatalogue = {L"catalogue.sqlite", 34545664,
    "d105c0f11a416e65b5989d9cdb2ffb92accb7f73c810308f6980221a774944cc"};

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
bool verify_catalogue_file(const std::wstring& dir) noexcept {
    try { return verify(dir, &kCatalogue, 1); } catch (...) { return false; }
}
}
