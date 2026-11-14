#include "engine.h"

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <string>

// Build as a separate console executable. Only aggregate event counts are
// printed; use only controlled WAV fixtures. This never opens a microphone.
int wmain(int argc, wchar_t** argv) {
    if (argc != 4 || (std::wstring(argv[3]) != L"--speech" && std::wstring(argv[3]) != L"--silence")) {
        std::wcerr << L"Usage: engine-smoke.exe <dossier-runtime> <test.wav> --speech|--silence\n";
        return 2;
    }
    const bool speech = std::wstring(argv[3]) == L"--speech";
    bool terminal = false;
    bool unexpected = false;
    unsigned partials = 0, finals = 0;
    std::wstring error;
    std::mutex mutex;
    std::condition_variable changed;
    const auto start = std::chrono::steady_clock::now();
    auto elapsed_ms = [&] {
        return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
    };
    try {
        doct::Engine engine([&](doct::EngineEvent event) {
            std::lock_guard<std::mutex> lock(mutex);
            using Kind = doct::EngineEventKind;
            if (terminal || event.generation != 1) unexpected = true;
            switch (event.kind) {
                case Kind::started:
                case Kind::capture_stopped:
                    unexpected = true;
                    break;
                case Kind::partial:
                    if (!event.text.empty()) ++partials;
                    break;
                case Kind::final:
                    if (event.text.empty()) unexpected = true;
                    else { ++finals; std::cout << "final_index=" << finals << " elapsed_ms=" << elapsed_ms() << std::endl; }
                    break;
                case Kind::error:
                    error = std::move(event.text);
                    terminal = true;
                    break;
                case Kind::stopped:
                    terminal = true;
                    break;
            }
            if (terminal) changed.notify_one();
        });
        if (!engine.start_wave(1, std::filesystem::absolute(argv[1]).wstring(), argv[2])) {
            std::wcerr << L"Démarrage du test refusé.\n";
            return 1;
        }
        {
            std::unique_lock<std::mutex> lock(mutex);
            if (!changed.wait_for(lock, std::chrono::seconds(90), [&] { return terminal; })) {
                std::wcerr << L"Délai de test dépassé.\n" << std::flush;
                std::quick_exit(3); // Allows a stuck third-party call to be diagnosed by CI.
            }
        }
        engine.shutdown();
        if (!error.empty()) {
            std::wcerr << error << L'\n';
            return 1;
        }
        std::cout << "partials_nonempty=" << partials << " finals_nonempty=" << finals
                  << " elapsed_ms=" << elapsed_ms() << '\n';
        const bool ok = speech ? finals > 0 : (partials == 0 && finals == 0);
        return (!unexpected && ok) ? 0 : 1;
    } catch (...) {
        std::wcerr << L"Impossible d’exécuter le test.\n";
        return 1;
    }
}
