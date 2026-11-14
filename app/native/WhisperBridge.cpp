#include "WhisperBridge.h"
#include "../macos/native/PauseState.h"
#include <whisper.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>

namespace {
void quiet_log(ggml_log_level, const char*, void*) {}
void backend_log(ggml_log_level level, const char* text, void*) {
    if (level == GGML_LOG_LEVEL_INFO && text &&
        std::strcmp(text, "whisper_backend_init: using BLAS backend\n") == 0)
        std::fputs("nv_accel backend=BLAS\n", stderr);
}
void timing_log(ggml_log_level, const char* text, void*) {
    // Upstream timing lines contain numeric counters only. Never forward model
    // logs, input paths, tokens or transcripts through this opt-in diagnostic.
    constexpr const char* prefix = "whisper_print_timings:";
    if (text && std::strncmp(text, prefix, std::strlen(prefix)) == 0) std::fputs(text, stderr);
}
class ModelFile {
    std::unique_ptr<FILE, decltype(&fclose)> file{nullptr, fclose};
public:
    whisper_model_loader loader{};
    explicit ModelFile(const char* path) {
#ifdef _WIN32
        file.reset(_wfopen(std::filesystem::u8path(path).c_str(), L"rb"));
#else
        file.reset(fopen(path, "rb"));
#endif
        if (!file) throw std::runtime_error("Model unavailable");
        loader.context = file.get();
        loader.read = [](void* ctx, void* output, size_t bytes) { return fread(output, 1, bytes, static_cast<FILE*>(ctx)); };
        loader.eof = [](void* ctx) { return feof(static_cast<FILE*>(ctx)) != 0; };
        loader.close = [](void*) {}; // Owned by this RAII guard through init.
    }
};
class Pipeline {
    std::unique_ptr<whisper_context, decltype(&whisper_free)> asr{nullptr, whisper_free};
    std::unique_ptr<whisper_vad_context, decltype(&whisper_vad_free)> vad{nullptr, whisper_vad_free};
    notevive::PauseState pauses;
    std::array<float, 512> frame{};
    size_t pending = 0;
    NVWhisperEmit emit = nullptr;
    void* output_context = nullptr;
    NVWhisperCancelled cancelled = nullptr;
    void* cancel_context = nullptr;
    bool benchmark_metrics = false;

    static int completed(void* ctx, const float* samples, size_t count) {
        return static_cast<Pipeline*>(ctx)->transcribe(samples, count);
    }
    int transcribe(const float* samples, size_t count) {
        if (cancelled && cancelled(cancel_context)) return -1;
        const auto start = std::chrono::steady_clock::now();
        auto params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
        params.language = "fr"; params.translate = false; params.no_context = true;
        params.n_threads = 4;
        params.print_progress = params.print_realtime = params.print_timestamps = params.print_special = false;
        params.vad = false; // One detector upstream; no second segmentation.
        params.abort_callback = [](void* ctx) {
            auto& self = *static_cast<Pipeline*>(ctx);
            return self.cancelled && self.cancelled(self.cancel_context);
        };
        params.abort_callback_user_data = this;
        if (benchmark_metrics) whisper_reset_timings(asr.get());
        const int status = whisper_full(asr.get(), params, samples, static_cast<int>(count));
        if (benchmark_metrics) {
            // Only one decoder runs in this worker. VAD and ASR calls are serial.
            whisper_log_set(timing_log, nullptr);
            whisper_print_timings(asr.get());
            whisper_log_set(quiet_log, nullptr);
        }
        if (status != 0) return -1;
        std::string result;
        const int segments = whisper_full_n_segments(asr.get());
        for (int i = 0; i < segments; ++i) {
            const auto* text = whisper_full_get_segment_text(asr.get(), i);
            if (!text) return -1;
            std::string part(text);
            const auto first = part.find_first_not_of(" \r\n\t");
            if (first == std::string::npos) continue;
            const auto last = part.find_last_not_of(" \r\n\t");
            if (!result.empty()) result += ' ';
            result += part.substr(first, last - first + 1);
            if (result.size() > 65536) return -1;
        }
        const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        return emit(output_context, result.c_str(), count, ms);
    }
    int step() {
        if (!whisper_vad_detect_speech_no_reset(vad.get(), frame.data(), static_cast<int>(frame.size())) ||
            whisper_vad_n_probs(vad.get()) != 1) return -1;
        const float p = whisper_vad_probs(vad.get())[0];
        if (!std::isfinite(p) || p < 0 || p > 1) return -1;
        const int status = pauses.frame(frame.data(), pending, p, completed, this);
        pending = 0;
        return status;
    }
public:
    Pipeline(const char* model_path, const char* vad_path, unsigned pause_ms) : pauses(pause_ms) {
        if (std::string(whisper_version()) != "1.8.5") throw std::runtime_error("Whisper version mismatch");
        const auto* metrics = std::getenv("NOTEVIVE_ASR_BENCH_METRICS");
        benchmark_metrics = metrics && std::strcmp(metrics, "1") == 0;
        whisper_log_set(benchmark_metrics ? backend_log : quiet_log, nullptr);
        ModelFile model(model_path);
        auto params = whisper_context_default_params(); params.use_gpu = false;
        asr.reset(whisper_init_with_params(&model.loader, params));
        whisper_log_set(quiet_log, nullptr);
        if (!asr) throw std::runtime_error("Whisper initialization failed");
        if (benchmark_metrics) std::fprintf(stderr, "nv_backend %s\n", whisper_print_system_info());
        ModelFile vad_file(vad_path);
        auto vparams = whisper_vad_default_context_params(); vparams.use_gpu = false; vparams.n_threads = 1;
        vad.reset(whisper_vad_init_with_params(&vad_file.loader, vparams));
        if (!vad) throw std::runtime_error("Silero initialization failed");
        reset();
    }
    void reset() { pending = 0; frame.fill(0); pauses.reset(); whisper_vad_reset_state(vad.get()); }
    void set_cancel(NVWhisperCancelled callback, void* ctx) { cancelled = callback; cancel_context = ctx; }
    int accept(const float* samples, size_t count, NVWhisperEmit callback, void* ctx) {
        emit = callback; output_context = ctx;
        while (count) {
            const size_t take = std::min(count, frame.size() - pending);
            std::copy_n(samples, take, frame.begin() + pending);
            samples += take; count -= take; pending += take;
            if (pending == frame.size() && step() != 0) return -1;
        }
        return 0;
    }
    int finish(NVWhisperEmit callback, void* ctx) {
        emit = callback; output_context = ctx;
        if (pending) { std::fill(frame.begin() + pending, frame.end(), 0); if (step() != 0) return -1; }
        const auto status = pauses.finish(completed, this); reset(); return status;
    }
};
}
extern "C" {
void* NVWhisperCreate(const char* model, const char* vad) {
    return NVWhisperCreateWithPause(model, vad, NV_SILERO_PAUSE_MS);
}
void* NVWhisperCreateWithPause(const char* model, const char* vad, unsigned pause_ms) {
    if (!model || !vad || !*model || !*vad || pause_ms < 96 || pause_ms > 3000) return nullptr;
    try { return new Pipeline(model, vad, pause_ms); } catch (...) { return nullptr; }
}
void NVWhisperDestroy(void* h) { delete static_cast<Pipeline*>(h); }
void NVWhisperReset(void* h) { if (h) static_cast<Pipeline*>(h)->reset(); }
void NVWhisperSetCancellation(void* h, NVWhisperCancelled fn, void* ctx) { if (h) static_cast<Pipeline*>(h)->set_cancel(fn, ctx); }
int NVWhisperAccept(void* h, const float* samples, size_t count, NVWhisperEmit fn, void* ctx) {
    if (!h || (!samples && count) || !fn || count > 30 * 16000) return -1;
    try { return static_cast<Pipeline*>(h)->accept(samples, count, fn, ctx); } catch (...) { return -1; }
}
int NVWhisperFinish(void* h, NVWhisperEmit fn, void* ctx) {
    if (!h || !fn) return -1;
    try { return static_cast<Pipeline*>(h)->finish(fn, ctx); } catch (...) { return -1; }
}
}
