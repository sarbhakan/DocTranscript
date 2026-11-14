#include "../macos/native/PauseState.h"
#include <cassert>
#include <iostream>

int main() {
    using notevive::PauseState;
    std::array<float, PauseState::hop> frame{};
    size_t emitted = 0, samples = 0;
    struct Result { size_t* emitted; size_t* samples; } result{&emitted, &samples};
    const auto collect = [](void* p, const float*, size_t n) {
        auto& r = *static_cast<Result*>(p); ++*r.emitted; *r.samples += n; return 0;
    };
    for (const unsigned milliseconds : {576u, 1200u}) {
        emitted = samples = 0;
        PauseState state(milliseconds);
        auto send = [&](float probability) {
            assert(state.frame(frame.data(), frame.size(), probability, collect, &result) == 0);
        };
        // Isolated detector spikes cannot produce ASR text.
        send(.9f); for (int i = 0; i < 100; ++i) send(.0f);
        assert(emitted == 0);
        const size_t quiet = (milliseconds + 31) / 32;
        for (int i = 0; i < 3; ++i) send(.9f);
        for (size_t i = 1; i < quiet; ++i) send(.0f);
        assert(emitted == 0);
        send(.0f); assert(emitted == 1);
        assert(samples == (PauseState::preroll_frames + 3 + quiet) * PauseState::hop);
        state.reset(); emitted = samples = 0;
        // Hard 30-second ceiling preserves every sample across continuation.
        const size_t count = PauseState::max_samples / PauseState::hop + 1;
        for (size_t i = 0; i < count; ++i) send(.9f);
        assert(state.finish(collect, &result) == 0);
        assert(emitted == 2 && samples == count * PauseState::hop);
        assert(state.finish(collect, &result) == 0 && emitted == 2);
    }
    std::cout << "Pause rounding, noise rejection, flush and bounded continuity: OK\n";
}
