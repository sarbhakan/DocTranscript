#include "engine.h"
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <initializer_list>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace doct;
using Kind = EngineEventKind;
constexpr std::wstring_view kText = L"Texte fictif de contrôle : œdème à gauche.";
bool terminal(const EngineEvent& event) {
    return event.kind == Kind::error || event.kind == Kind::stopped;
}
const char* event_name(Kind kind) {
    switch (kind) {
    case Kind::started: return "started";
    case Kind::partial: return "partial";
    case Kind::final: return "final";
    case Kind::capture_stopped: return "capture_stopped";
    case Kind::stopped: return "stopped";
    case Kind::error: return "error";
    }
    return "unknown";
}
const char* error_code(std::wstring_view text) {
    if (text == Engine::cpu_requirement()) return "unsupported_cpu";
    if (text.find(L"incomplet") != text.npos) return "truncated";
    if (text.find(L"interrompu") != text.npos) return "child_exit";
    if (text.find(L"inattendue") != text.npos) return "unexpected_response";
    if (text.find(L"à temps") != text.npos) return "watchdog";
    if (text.find(L"non confirmé") != text.npos) return "unconfirmed_capture_stop";
    return text.empty() ? "blank" : "other";
}
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) return 2;
    std::mutex mutex;
    std::condition_variable changed;
    std::vector<EngineEvent> events;
    const auto runtime = std::filesystem::absolute(argv[1]).wstring();
    Engine engine([&](EngineEvent event) {
        std::lock_guard<std::mutex> lock(mutex);
        events.push_back(std::move(event));
        changed.notify_one();
    });
    auto wait = [&](auto predicate, std::chrono::seconds timeout = std::chrono::seconds(7)) {
        std::unique_lock<std::mutex> lock(mutex);
        if (!changed.wait_for(lock, timeout, [&] { return predicate(events); }))
            throw std::runtime_error("Supervisor event timed out");
    };
    std::uint64_t generation = 0;
    std::string_view test;
    std::vector<Kind> wanted;
    auto run = [&](const char* name, const wchar_t* command, std::initializer_list<Kind> expected,
                   std::wstring_view expected_error = {}, const std::wstring& directory = {}) {
        test = name;
        wanted.assign(expected);
        const bool cancel = std::wstring_view(command) == L"ignore-cancel";
        const bool stop = std::wstring_view(command) == L"ignore-stop";
        {
            std::lock_guard<std::mutex> lock(mutex);
            events.clear();
        }
        if (!engine.start_wave(++generation, directory.empty() ? runtime : directory, command))
            throw std::runtime_error("Start rejected");
        if (cancel || stop) {
            wait([](const auto& e) { return !e.empty(); });
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (events.size() != 1 || events.front().kind != Kind::started)
                    throw std::runtime_error("Expected active dictation before interruption");
            }
            if (cancel) engine.cancel();
            else engine.stop();
        }
        wait([](const auto& e) { return !e.empty() && terminal(e.back()); });
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (events.size() != expected.size()) throw std::runtime_error("Wrong event count");
            std::size_t i = 0;
            for (const auto kind : expected) {
                const auto& event = events[i++];
                if (event.kind != kind || event.generation != generation || event.capture_unconfirmed)
                    throw std::runtime_error("Wrong event, session or microphone state");
                if (event.kind == Kind::final && event.text != kText)
                    throw std::runtime_error("Missing or truncated transcript");
                if (event.kind == Kind::error && (event.text.empty() ||
                    (!expected_error.empty() && event.text.find(expected_error) == std::wstring::npos)))
                    throw std::runtime_error("Wrong failure reason");
            }
        }
    };
    auto valid = [&] { run("restart", L"valid", {Kind::started, Kind::final, Kind::stopped}); };
    try {
        engine.refuse_cpu_for_test(true);
        run("unsupported CPU does not spawn the worker", L"valid", {Kind::error}, Engine::cpu_requirement());
        run("unsupported CPU is refused before runtime verification", L"valid", {Kind::error}, Engine::cpu_requirement(),
            (std::filesystem::path(runtime) / L"missing-cpu-guard-test-runtime").wstring());
        engine.refuse_cpu_for_test(false);
        valid();
        run("fragmented frame", L"fragmented", {Kind::started, Kind::final, Kind::stopped});
        run("crash after final", L"crash", {Kind::started, Kind::final, Kind::error});
        valid();
        run("oversized header", L"oversized", {Kind::error});
        valid();
        run("wrong generation", L"wrong-generation", {Kind::started, Kind::error}, L"inattendue");
        valid();
        run("truncated payload after complete frames", L"truncated", {Kind::started, Kind::final, Kind::error}, L"incomplet");
        valid();
        run("live watchdog", L"watchdog", {Kind::started, Kind::final, Kind::error}, L"à temps");
        valid();
        run("ignored stop", L"ignore-stop", {Kind::started, Kind::final, Kind::error}, L"à temps");
        valid();
        run("ignored cancel", L"ignore-cancel", {Kind::started, Kind::stopped});
        valid();
        engine.shutdown();
    } catch (const std::exception& error) {
        std::cerr << test << ": " << error.what() << '\n';
        std::lock_guard<std::mutex> lock(mutex);
        std::cerr << "Generation " << generation << ", expected:";
        for (const auto kind : wanted) std::cerr << ' ' << event_name(kind);
        std::cerr << "\nReceived:";
        for (const auto& event : events) {
            std::cerr << ' ' << event_name(event.kind) << "(gen=" << event.generation
                      << ", mic_unconfirmed=" << event.capture_unconfirmed << ", utf16_units=" << event.text.size();
            if (event.kind == Kind::error) std::cerr << ", reason=" << error_code(event.text);
            std::cerr << ')';
        }
        std::cerr << '\n';
        return 1;
    }
    std::cout << "CPU refusal, partial frames, wrong generation, crash after transcript, watchdog, stop, cancel, restart: OK\n";
    return 0;
}
