// Portable replay of the streaming recognizer settings in app/windows/engine.cpp.
// Read real audio via the Python harness; no capture, UI, or file access here.
#include "c-api.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <stdexcept>
#include <cstring>

#if defined(_WIN32)
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

extern "C" {
EXPORT const SherpaOnnxOnlineRecognizer *nv_zipformer_create(const char *model_directory, int threads) noexcept {
    if (!model_directory || (threads != 2 && threads != 4)) return nullptr;
    try {
        const auto directory = std::filesystem::u8path(model_directory);
        auto str = [&](const char *name) {
            const auto path = (directory / name).u8string();
            return std::string(path.begin(), path.end());
        };
        const auto encoder = str("encoder.onnx"), decoder = str("decoder.onnx"),
                   joiner = str("joiner.onnx"), tokens = str("tokens.txt");
        SherpaOnnxOnlineRecognizerConfig config{};
        config.feat_config.sample_rate = 16000;
        config.feat_config.feature_dim = 80;
        config.model_config.transducer.encoder = encoder.c_str();
        config.model_config.transducer.decoder = decoder.c_str();
        config.model_config.transducer.joiner = joiner.c_str();
        config.model_config.tokens = tokens.c_str();
        config.model_config.provider = "cpu";
        config.model_config.num_threads = threads;
        config.decoding_method = "greedy_search";
        config.enable_endpoint = 1;
        config.rule1_min_trailing_silence = 2.4f;
        config.rule2_min_trailing_silence = 1.2f;
        config.rule3_min_utterance_length = 20.0f;
        return SherpaOnnxCreateOnlineRecognizer(&config);
    } catch (...) { return nullptr; }
}

EXPORT void nv_zipformer_destroy(const SherpaOnnxOnlineRecognizer *handle) noexcept {
    if (handle) SherpaOnnxDestroyOnlineRecognizer(handle);
}

EXPORT void nv_zipformer_free(char *text) noexcept { delete[] text; }

EXPORT char *nv_zipformer_run(const SherpaOnnxOnlineRecognizer *handle, const float *pcm,
                            int32_t size, int32_t *first_ms, double *stop_ms) noexcept {
    if (!handle || !pcm || size <= 0 || !first_ms || !stop_ms) return nullptr;
    try {
        const auto deleter = &SherpaOnnxDestroyOnlineStream;
        std::unique_ptr<const SherpaOnnxOnlineStream, decltype(deleter)> stream(
            SherpaOnnxCreateOnlineStream(handle), deleter);
        if (!stream) return nullptr;
        std::string committed;
        bool signal_seen = false;
        bool have_samples = false;
        *first_ms = -1;
        *stop_ms = 0;
        auto decode = [&] {
            int n = 0;
            while (SherpaOnnxIsOnlineStreamReady(handle, stream.get())) {
                if (++n > 256) throw std::runtime_error("decode not progressing");
                SherpaOnnxDecodeOnlineStream(handle, stream.get());
            }
            return n != 0;
        };
        auto text = [&] {
            const auto close = &SherpaOnnxDestroyOnlineRecognizerResult;
            std::unique_ptr<const SherpaOnnxOnlineRecognizerResult, decltype(close)> result(
                SherpaOnnxGetOnlineStreamResult(handle, stream.get()), close);
            return result && result->text ? std::string(result->text) : std::string{};
        };
        auto commit = [&](const std::string &value) {
            if (value.empty()) return;
            if (!committed.empty()) committed += ' ';
            committed += value;
        };
        constexpr int packet = 320;
        for (int32_t i = 0; i < size; i += packet) {
            const auto count = std::min<int32_t>(packet, size - i);
            signal_seen = signal_seen || std::any_of(pcm + i, pcm + i + count, [](float v) { return v != 0.f; });
            have_samples = true;
            SherpaOnnxOnlineStreamAcceptWaveform(stream.get(), 16000, pcm + i, count);
            if (!decode()) continue;
            const auto partial = signal_seen ? text() : std::string{};
            if (!partial.empty() && *first_ms < 0) *first_ms = (i + count) / 16;
            if (SherpaOnnxOnlineStreamIsEndpoint(handle, stream.get())) {
                commit(partial);
                SherpaOnnxOnlineStreamReset(handle, stream.get());
                signal_seen = false;
                have_samples = false;
            }
        }
        if (have_samples && signal_seen) {
            const auto start = std::chrono::steady_clock::now();
            constexpr std::array<float, 4800> tail{};
            SherpaOnnxOnlineStreamAcceptWaveform(stream.get(), 16000, tail.data(), tail.size());
            SherpaOnnxOnlineStreamInputFinished(stream.get());
            decode();
            commit(text());
            *stop_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        }
        auto output = std::make_unique<char[]>(committed.size() + 1);
        std::memcpy(output.get(), committed.c_str(), committed.size() + 1);
        return output.release();
    } catch (...) { return nullptr; }
}
} // extern C
