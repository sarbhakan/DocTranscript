#include "../native/PauseState.h"

#include <cassert>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <vector>

namespace {
using notevive::PauseState;

int collect(void *context, const float *audio, size_t count) {
    static_cast<std::vector<std::vector<float>> *>(context)->emplace_back(audio, audio + count);
    return 0;
}

void state_tests() {
    PauseState state;
    std::vector<std::vector<float>> segments;
    auto frame = [&](float probability, float marker, size_t count = PauseState::hop) {
        std::array<float, PauseState::hop> audio;
        audio.fill(marker);
        assert(state.frame(audio.data(), count, probability, collect, &segments) == 0);
    };
    for (unsigned i = 0; i < 20; ++i) frame(0, float(i));
    frame(.9f, 20); // isolated noise burst
    for (unsigned i = 21; i < 26; ++i) frame(.05f, float(i));
    assert(segments.empty());
    frame(.9f, 26);
    frame(.6f, 27);
    frame(.4f, 28);
    for (unsigned i = 1; i < PauseState::pause_frames; ++i) frame(.05f, 30);
    assert(segments.empty());
    frame(.05f, 31);
    assert(segments.size() == 1);
    assert(segments[0].size() == (PauseState::preroll_frames + 3 + PauseState::pause_frames) * PauseState::hop);
    assert(segments[0][0] == 18 && segments[0][PauseState::preroll_frames * PauseState::hop] == 26);

    // An explicit stop commits only qualified speech and includes the final partial hop.
    for (int i = 0; i < 3; ++i) frame(.9f, 1);
    frame(.1f, 2, 37);
    assert(state.finish(collect, &segments) == 0 && segments.size() == 2);
    assert(segments[1].size() == 3 * PauseState::hop + 37 && segments[1].back() == 2);
    assert(state.finish(collect, &segments) == 0 && segments.size() == 2);

    // Without a pause the hard bound emits multiple clips, with no duplication or gap.
    const size_t full = PauseState::max_samples / PauseState::hop;
    for (size_t i = 0; i < full + 1; ++i) frame(.9f, float(i));
    assert(state.finish(collect, &segments) == 0 && segments.size() == 4);
    assert(segments[2].size() == PauseState::max_samples && segments[3].size() == PauseState::hop);
    assert(segments[2].back() == float(full - 1) && segments[3].front() == float(full));

    frame(.9f, 1);
    frame(.9f, 1);
    state.reset();
    assert(state.finish(collect, &segments) == 0 && segments.size() == 4);
}

void model_tests(const char *model, const char *speech_raw) {
    void *vad = nv_silero_create(model);
    assert(vad);
    std::vector<std::vector<float>> segments;
    std::vector<float> silence(16000, 0);
    assert(nv_silero_accept(vad, silence.data(), silence.size(), collect, &segments) == 0);
    assert(nv_silero_finish(vad, collect, &segments) == 0 && segments.empty());

    std::ifstream raw(speech_raw, std::ios::binary);
    assert(raw);
    std::vector<float> speech;
    for (int16_t value; raw.read(reinterpret_cast<char *>(&value), sizeof(value));) {
        speech.push_back(static_cast<float>(value) / 32768);
    }
    assert(speech.size() > 16000);
    assert(nv_silero_accept(vad, speech.data(), speech.size(), collect, &segments) == 0);
    assert(nv_silero_accept(vad, silence.data(), silence.size(), collect, &segments) == 0);
    assert(!segments.empty()); // do not require an explicit stop to get the text
    assert(nv_silero_finish(vad, collect, &segments) == 0);
    const auto expected = segments;
    segments.clear();

    // AVAudioConverter packets need not align with the VAD's hop boundaries.
    speech.insert(speech.end(), silence.begin(), silence.end());
    for (size_t offset = 0; offset < speech.size();) {
        const size_t count = std::min<size_t>(733, speech.size() - offset);
        assert(nv_silero_accept(vad, speech.data() + offset, count, collect, &segments) == 0);
        offset += count;
    }
    assert(!segments.empty());
    assert(nv_silero_finish(vad, collect, &segments) == 0 && segments == expected);

    const size_t first = segments.size();
    speech.resize(speech.size() - silence.size());
    assert(nv_silero_accept(vad, speech.data(), speech.size(), collect, &segments) == 0);
    assert(nv_silero_finish(vad, collect, &segments) == 0);
    assert(segments.size() > first);
    nv_silero_destroy(vad);
}
} // namespace

int main(int argc, char **argv) {
    if (argc != 1 && argc != 3) {
        std::cerr << "Usage: SileroPauseTests [silero_vad.onnx speech-16k-mono-s16le.pcm]\n";
        return 2;
    }
    state_tests();
    if (argc == 3) model_tests(argv[1], argv[2]);
    std::cout << "Silero pause checks passed\n";
}
