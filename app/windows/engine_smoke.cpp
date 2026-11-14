#include "engine.h"

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>
#include <string>
#include <string_view>

namespace {
bool space(wchar_t ch) {
    return std::wstring_view(L" \t\r\n\v\f\u00a0\u202f").find(ch) != std::wstring_view::npos;
}

bool separator(wchar_t ch) {
    return space(ch) || std::wstring_view(L",.;:!?()[]{}\"'«»“”’–—…").find(ch) != std::wstring_view::npos;
}

bool matches(std::wstring_view text, std::size_t offset, std::wstring_view expected) {
    if (expected.size() > text.size() - offset) return false;
    for (wchar_t want : expected) {
        wchar_t actual = text[offset++];
        if (actual >= L'A' && actual <= L'Z') actual += L'a' - L'A';
        if (actual != want) return false;
    }
    return true;
}

bool prozac_20_mg(std::wstring_view text) {
    // Assert the local association in px-826. Match in place; do not remove
    // punctuation globally, which could turn 2,0 or 20/10 into another value.
    constexpr std::wstring_view drug = L"prozac";
    for (std::size_t i = 0; i < text.size(); ++i) {
        if ((i && !separator(text[i - 1])) || !matches(text, i, drug)) continue;
        auto next = i + drug.size();
        if (next == text.size() || !separator(text[next])) continue;
        while (next < text.size() && separator(text[next])) ++next;
        if (matches(text, next, L"20")) {
            if (text[next - 1] == L'.' || text[next - 1] == L',') continue; // .20 or ,20 without a leading zero
            next += 2;
        } else if (matches(text, next, L"vingt")) {
            next += 5;
            if (next == text.size() || !separator(text[next])) continue;
        } else {
            continue;
        }
        // Accept 20mg but no other number, fraction, or medication before the unit.
        while (next < text.size() && separator(text[next])) ++next;
        for (const auto unit : {std::wstring_view(L"mg"), std::wstring_view(L"milligramme"),
                                std::wstring_view(L"milligrammes")}) {
            if (!matches(text, next, unit)) continue;
            auto end = next + unit.size();
            if (end < text.size() && !separator(text[end])) continue;
            while (end < text.size() && space(text[end])) ++end;
            if (end == text.size() || text[end] != L'/') return true; // No concentration such as mg/mL.
        }
    }
    return false;
}
} // namespace

// Separate console test for controlled WAVs. --speech refers to px-826 only.
// Prints counts, timings and the expected drug-strength check; never the transcript.
int wmain(int argc, wchar_t** argv) {
    static_assert(sizeof(wchar_t) == 2, "Windows UTF-16 required");
    const bool regression = argc == 5 && std::wstring(argv[3]) == L"--regression";
    if (!regression && (argc != 4 || (std::wstring(argv[3]) != L"--speech" && std::wstring(argv[3]) != L"--silence"))) {
        std::wcerr << L"Usage : engine-smoke.exe <dossier-runtime> <px-826.wav> --speech\n"
                      L"        engine-smoke.exe <dossier-runtime> <silence.wav> --silence\n"
                      L"        engine-smoke.exe <dossier-runtime> <fixture.wav> --regression <sortie.txt>\n";
        return 2;
    }
    const bool speech = regression || std::wstring(argv[3]) == L"--speech";
    bool terminal = false;
    bool unexpected = false;
    unsigned partials = 0, finals = 0;
    bool engine_error = false;
    std::wstring transcript;
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
                    else {
                        if (speech) {
                            if (!transcript.empty()) transcript += L' ';
                            transcript += event.text;
                        }
                        ++finals;
                        std::cout << "final_index=" << finals << " elapsed_ms=" << elapsed_ms() << std::endl;
                    }
                    break;
                case Kind::error:
                    engine_error = true;
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
        if (engine_error) {
            std::wcerr << L"Le moteur a renvoyé une erreur pendant le test.\n";
            return 1;
        }
        std::cout << "partials_nonempty=" << partials << " finals_nonempty=" << finals
                  << " elapsed_ms=" << elapsed_ms() << '\n';
        if (regression) {
            // Test-only output for licensed fictitious fixtures; never stdout.
            // UTF-16LE preserves exactly what the Windows UI receives.
            const std::filesystem::path report(argv[4]);
            if (std::filesystem::exists(report)) return 2;
            std::ofstream output(report, std::ios::binary);
            output.write("\xff\xfe", 2);
            output.write(reinterpret_cast<const char*>(transcript.data()),
                         static_cast<std::streamsize>(transcript.size() * sizeof(wchar_t)));
            output.close();
            if (!output) return 2;
        }
        const bool paired = speech && !regression && prozac_20_mg(transcript);
        if (speech && !regression) std::cout << "prozac_20_mg=" << (paired ? "true" : "false") << '\n';
        const bool ok = regression ? finals > 0 : (speech ? paired : (partials == 0 && finals == 0));
        return (!unexpected && ok) ? 0 : 1;
    } catch (...) {
        std::wcerr << L"Impossible d’exécuter le test.\n";
        return 1;
    }
}
