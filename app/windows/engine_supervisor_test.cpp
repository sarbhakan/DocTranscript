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
    auto run = [&](const char* name, const wchar_t* command, std::initializer_list<Kind> expected,
                   std::wstring_view expected_error = {}) {
        test = name;
        const bool cancel = std::wstring_view(command) == L"ignore-cancel";
        const bool stop = std::wstring_view(command) == L"ignore-stop";
        {
            std::lock_guard<std::mutex> lock(mutex);
            events.clear();
        }
        if (!engine.start_wave(++generation, runtime, command)) throw std::runtime_error("Start rejected");
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
        run("fragmented frame", L"fragmented", {Kind::started, Kind::final, Kind::stopped});
        run("crash after final", L"crash", {Kind::started, Kind::final, Kind::error});
        valid();
        run("oversized header", L"oversized", {Kind::error});
        valid();
        run("wrong generation", L"wrong-generation", {Kind::started, Kind::error}, L"inattendue");
        valid();
        run("truncated payload", L"truncated", {Kind::started, Kind::error});
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
        return 1;
    }
    std::cout << "Partial frames, wrong generation, crash after transcript, watchdog, stop, cancel, restart: OK\n";
}
