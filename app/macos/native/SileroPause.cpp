#include "PauseState.h"

#include <onnxruntime_cxx_api.h>

#include <array>
#include <cmath>
#include <cstdint>

namespace {
class SileroPause {
public:
    explicit SileroPause(const char *model_path) {
        env_.DisableTelemetryEvents();
        Ort::SessionOptions options;
        options.SetIntraOpNumThreads(1).SetInterOpNumThreads(1).SetExecutionMode(ORT_SEQUENTIAL);
        session_ = Ort::Session(env_, model_path, options);

        // The ONNX export consumes 64 previous samples and 512 new samples.
        // Reuse the input/output storage; stateN is copied back into state.
        const int64_t audio_shape[] = {1, static_cast<int64_t>(audio_.size())};
        const int64_t state_shape[] = {2, 1, 128};
        const int64_t probability_shape[] = {1, 1};
        inputs_[0] = Ort::Value::CreateTensor<float>(memory_, audio_.data(), audio_.size(), audio_shape, 2);
        inputs_[1] = Ort::Value::CreateTensor<float>(memory_, state_.data(), state_.size(), state_shape, 3);
        inputs_[2] = Ort::Value::CreateTensor<int64_t>(memory_, &sample_rate_, 1, nullptr, 0);
        outputs_[0] = Ort::Value::CreateTensor<float>(memory_, &probability_, 1, probability_shape, 2);
        outputs_[1] = Ort::Value::CreateTensor<float>(memory_, state_next_.data(), state_next_.size(), state_shape, 3);
    }

    void reset() {
        audio_.fill(0);
        state_.fill(0);
        state_next_.fill(0);
        pending_ = 0;
        pause_.reset();
    }

    int accept(const float *samples, size_t count, NVSileroEmit emit, void *context) {
        while (count != 0) {
            const size_t take = std::min(count, notevive::PauseState::hop - pending_);
            std::copy_n(samples, take, audio_.begin() + context_size + pending_);
            pending_ += take;
            samples += take;
            count -= take;
            if (pending_ == notevive::PauseState::hop && run_frame(emit, context) != 0) return -1;
        }
        return 0;
    }

    int finish(NVSileroEmit emit, void *context) {
        if (pending_ != 0) {
            // Pad only the VAD probe; send the exact original samples to ASR.
            std::fill(audio_.begin() + context_size + pending_, audio_.end(), 0);
            if (run_frame(emit, context) != 0) return -1;
        }
        const int status = pause_.finish(emit, context);
        reset();
        return status;
    }

private:
    static constexpr size_t context_size = 64;
    Ort::Env env_{ORT_LOGGING_LEVEL_ERROR, "NoteVive"};
    Ort::Session session_{nullptr};
    Ort::MemoryInfo memory_{Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault)};
    Ort::RunOptions run_options_;
    std::array<float, context_size + notevive::PauseState::hop> audio_{};
    std::array<float, 256> state_{}, state_next_{};
    int64_t sample_rate_ = 16'000;
    float probability_ = 0;
    std::array<Ort::Value, 3> inputs_{Ort::Value(nullptr), Ort::Value(nullptr), Ort::Value(nullptr)};
    std::array<Ort::Value, 2> outputs_{Ort::Value(nullptr), Ort::Value(nullptr)};
    size_t pending_ = 0;
    notevive::PauseState pause_;

    int run_frame(NVSileroEmit emit, void *context) {
        const char *input_names[] = {"input", "state", "sr"};
        const char *output_names[] = {"output", "stateN"};
        session_.Run(run_options_, input_names, inputs_.data(), inputs_.size(),
                     output_names, outputs_.data(), outputs_.size());
        if (!std::isfinite(probability_) || probability_ < 0 || probability_ > 1) return -1;
        state_ = state_next_;
        const int status = pause_.frame(audio_.data() + context_size, pending_, probability_, emit, context);
        std::copy_n(audio_.end() - context_size, context_size, audio_.begin());
        pending_ = 0;
        return status;
    }
};
} // namespace

extern "C" {
void *nv_silero_create(const char *model_path) {
    if (!model_path || !*model_path) return nullptr;
    try {
        return new SileroPause(model_path);
    } catch (...) {
        return nullptr;
    }
}

void nv_silero_destroy(void *vad) {
    delete static_cast<SileroPause *>(vad);
}

void nv_silero_reset(void *vad) {
    if (vad) static_cast<SileroPause *>(vad)->reset();
}

int nv_silero_accept(void *vad, const float *pcm16k, size_t count, NVSileroEmit emit, void *context) {
    if (!vad || (!pcm16k && count != 0) || !emit) return -1;
    try {
        return static_cast<SileroPause *>(vad)->accept(pcm16k, count, emit, context);
    } catch (...) {
        return -1;
    }
}

int nv_silero_finish(void *vad, NVSileroEmit emit, void *context) {
    if (!vad || !emit) return -1;
    try {
        return static_cast<SileroPause *>(vad)->finish(emit, context);
    } catch (...) {
        return -1;
    }
}
}
