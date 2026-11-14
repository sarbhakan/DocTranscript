// Test-only child. Never distributed with the product.
#include <windows.h>
#include "worker_protocol.h"
#include <array>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {
using namespace doct::wire;
constexpr std::wstring_view kText = L"Texte fictif de contrôle : œdème à gauche.";

bool transfer(HANDLE pipe, void* data, DWORD size, bool write) {
    auto* cursor = static_cast<unsigned char*>(data);
    while (size) {
        DWORD count = 0;
        const BOOL ok = write ? WriteFile(pipe, cursor, size, &count, nullptr)
                              : ReadFile(pipe, cursor, size, &count, nullptr);
        if (!ok || !count) return false;
        cursor += count;
        size -= count;
    }
    return true;
}

bool receive(HANDLE input, Header& header, std::wstring& text) {
    std::array<std::uint8_t, header_size> bytes{};
    if (!transfer(input, bytes.data(), static_cast<DWORD>(bytes.size()), false)) return false;
    header = decode(bytes);
    text.resize(header.bytes / 2);
    return transfer(input, text.data(), header.bytes, false);
}

void send(HANDLE output, Kind kind, std::uint64_t generation,
          std::wstring text = {}, bool fragmented = false) {
    const auto size = static_cast<DWORD>(text.size() * 2);
    auto header = encode({kind, generation, size, 0});
    // Split the header and UTF-16 payload across writes at odd offsets.
    if (fragmented) {
        if (size <= 3) throw std::runtime_error("Fixture payload too short to split");
        if (!transfer(output, header.data(), 7, true)) ExitProcess(8);
        Sleep(40);
        if (!transfer(output, header.data() + 7, header_size - 7, true) ||
            !transfer(output, text.data(), 3, true)) ExitProcess(8);
        Sleep(40);
        if (!transfer(output, reinterpret_cast<unsigned char*>(text.data()) + 3, size - 3, true)) ExitProcess(8);
        return;
    }
    if (!transfer(output, header.data(), static_cast<DWORD>(header.size()), true) ||
        !transfer(output, text.data(), size, true)) ExitProcess(8);
}

void require_request(HANDLE input, Kind kind, std::uint64_t generation) {
    Header header{};
    std::wstring text;
    if (!receive(input, header, text) || header.kind != kind || header.generation != generation ||
        header.bytes || header.flags) throw std::runtime_error("Unexpected fixture request");
}
}

int wmain() {
    static_assert(sizeof(wchar_t) == 2);
    const auto input = GetStdHandle(STD_INPUT_HANDLE), output = GetStdHandle(STD_OUTPUT_HANDLE);
    try {
        Header h{};
        std::wstring test;
        while (receive(input, h, test)) {
            if (h.kind == quit) return 0;
            if (h.kind != start || !h.generation || h.flags != 1) return 3;
            if (test == L"oversized") {
                auto bytes = encode({final, h.generation, static_cast<std::uint32_t>(max_bytes + 2), 0});
                if (!transfer(output, bytes.data(), static_cast<DWORD>(bytes.size()), true)) return 8;
                Sleep(INFINITE);
            }
            send(output, started, h.generation);
            if (test == L"wrong-generation") {
                send(output, final, h.generation + 1, std::wstring(kText));
                Sleep(INFINITE);
            }
            if (test == L"truncated") {
                auto header = encode({final, h.generation, 14, 0});
                unsigned char incomplete[]{'x', 0, 'y'};
                if (!transfer(output, header.data(), static_cast<DWORD>(header.size()), true) ||
                    !transfer(output, incomplete, sizeof(incomplete), true)) return 8;
                ExitProcess(7);
            }
            if (test == L"crash") {
                send(output, final, h.generation, std::wstring(kText));
                // No quit logic, terminal frame or C++ cleanup.
                TerminateProcess(GetCurrentProcess(), 7);
                return 7;
            }
            if (test == L"watchdog") {
                // Stay active longer than the injected live deadline; then stop
                // making progress while remaining alive and holding the pipes.
                for (int i = 0; i < 9; ++i) {
                    Sleep(250);
                    send(output, progress, h.generation);
                }
                send(output, final, h.generation, std::wstring(kText));
                Sleep(INFINITE);
            }
            if (test == L"ignore-stop") {
                require_request(input, stop, h.generation);
                send(output, final, h.generation, std::wstring(kText));
                for (;;) {
                    send(output, progress, h.generation);
                    Sleep(125);
                }
            }
            if (test == L"ignore-cancel") {
                require_request(input, cancel, h.generation);
                send(output, final, h.generation, std::wstring(kText));
                Sleep(INFINITE);
            }
            if (test != L"valid" && test != L"fragmented") return 4;
            send(output, final, h.generation, std::wstring(kText), test == L"fragmented");
            send(output, stopped, h.generation);
        }
    } catch (...) { return 5; }
    return 0;
}
