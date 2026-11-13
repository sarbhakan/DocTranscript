#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

namespace doct {

enum class EngineEventKind { started, partial, final, capture_stopped, stopped, error };

struct EngineEvent {
    EngineEventKind kind;
    std::uint64_t generation;
    std::wstring text;
    bool capture_unconfirmed = false;
};

class Engine {
public:
    // Events arrive in order on one worker. Post them to the UI and return.
    // A partial replaces the provisional text; a final appends one segment.
    // stopped/error is terminal. Do not call shutdown from the callback.
    using Callback = std::function<void(EngineEvent)>;

    explicit Engine(Callback callback);
    ~Engine();
    Engine(const Engine&) = delete;
    Engine& operator=(const Engine&) = delete;

    bool start(std::uint64_t generation, std::wstring model_directory);
    // Smoke test only: same recognizer and segmentation without opening WinMM.
    bool start_wave(std::uint64_t generation, std::wstring model_directory,
                    std::wstring wave_path);
    void stop();   // Stop the microphone, then finish the captured audio.
    void cancel(); // Stop the microphone and discard pending audio/provisional text.
    void shutdown();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace doct
