#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include "local_engine.h"
#include "worker_protocol.h"
#include <atomic>
#include <mutex>

namespace {
bool transfer(HANDLE pipe, void* data, DWORD length, bool write) {
    auto* ptr = static_cast<char*>(data);
    while (length) {
        DWORD done = 0;
        const BOOL ok = write ? WriteFile(pipe, ptr, length, &done, nullptr)
                              : ReadFile(pipe, ptr, length, &done, nullptr);
        if (!ok || !done) return false;
        ptr += done; length -= done;
    }
    return true;
}
}

int wmain(int argc, wchar_t** argv) {
    static_assert(sizeof(wchar_t) == 2);
    if (argc != 2) return 2;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    const HANDLE input = GetStdHandle(STD_INPUT_HANDLE), output = GetStdHandle(STD_OUTPUT_HANDLE);
    std::mutex writing;
    std::atomic<std::uint64_t> active{0};
    doct::LocalEngine engine([&](doct::EngineEvent event) {
        const auto kind = static_cast<doct::wire::Kind>(doct::wire::started + static_cast<int>(event.kind));
        if (event.text.size() > doct::wire::max_bytes / 2) ExitProcess(5);
        auto header = doct::wire::encode({kind, event.generation,
            static_cast<std::uint32_t>(event.text.size() * 2), event.capture_unconfirmed ? 1u : 0u});
        std::lock_guard<std::mutex> lock(writing);
        if (doct::wire::terminal(kind)) active.store(0);
        if (!transfer(output, header.data(), static_cast<DWORD>(header.size()), true) ||
            !transfer(output, event.text.data(), static_cast<DWORD>(event.text.size() * 2), true)) ExitProcess(6);
    }, [&] {
        const auto generation = active.load();
        if (!generation) return;
        auto header = doct::wire::encode({doct::wire::progress, generation, 0, 0});
        std::lock_guard<std::mutex> lock(writing);
        if (!transfer(output, header.data(), static_cast<DWORD>(header.size()), true)) ExitProcess(6);
    });
    try {
        for (;;) {
            std::array<std::uint8_t, doct::wire::header_size> bytes{};
            if (!transfer(input, bytes.data(), static_cast<DWORD>(bytes.size()), false)) break;
            const auto h = doct::wire::decode(bytes);
            if (h.kind > doct::wire::quit) return 3;
            std::wstring payload(h.bytes / 2, L'\0');
            if (!transfer(input, payload.data(), h.bytes, false)) break;
            if (h.kind == doct::wire::quit) break;
            if (h.kind == doct::wire::start) {
                if (!h.generation || active.load() || payload.find(L'\0') != std::wstring::npos ||
                    (h.flags == 0 && !payload.empty()) || (h.flags == 1 && payload.empty())) return 3;
                active.store(h.generation);
                const bool ok = h.flags ? engine.start_wave(h.generation, argv[1], payload)
                                        : engine.start(h.generation, argv[1]);
                if (!ok) return 4;
            } else {
                if (h.bytes || h.flags) return 3;
                if (active.load() != h.generation) continue;
                if (h.kind == doct::wire::stop) engine.stop();
                else engine.cancel();
            }
        }
    } catch (...) { return 3; }
    engine.shutdown();
    return 0;
}
