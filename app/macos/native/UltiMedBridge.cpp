#include "UltiMedBridge.h"
#include "UltiMedLexicalContext.h"
#include <onnxruntime_cxx_api.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
constexpr int32_t kMaximumSamples = 30 * 16000;
constexpr int64_t kFeatures = 128;
constexpr int64_t kEncoderSize = 1024;
constexpr int64_t kStateWidth = 640;
constexpr int32_t kBlank = 8192;
constexpr int32_t kVocab = kBlank + 1;
constexpr int32_t kDurationBins = 5;
constexpr int kMaximumTokensPerFrame = 10;

void require(bool ok) {
    if (!ok) throw std::runtime_error("Incompatible UltiMed tensor or vocabulary");
}

std::vector<std::string> loadVocab(const std::filesystem::path &path) {
    std::ifstream file(path);
    require(bool(file));
    std::vector<std::string> words(kVocab);
    std::string line;
    int next = 0;
    const std::string whitespaceMarker = "\xe2\x96\x81";
    while (std::getline(file, line)) {
        auto split = line.rfind(' ');
        require(split != std::string::npos && split > 0 && next < kVocab);
        require(line.substr(split + 1) == std::to_string(next));
        auto word = line.substr(0, split);
        for (size_t pos = 0; (pos = word.find(whitespaceMarker, pos)) != std::string::npos; ++pos) {
            word.replace(pos, whitespaceMarker.size(), " ");
        }
        words[next++] = std::move(word);
    }
    require(next == kVocab && words[kBlank] == "<blk>");
    return words;
}

Ort::SessionOptions options() {
    Ort::SessionOptions opts;
    opts.SetExecutionMode(ORT_SEQUENTIAL);
    opts.SetInterOpNumThreads(1);
    opts.SetIntraOpNumThreads(4);
    return opts;
}

class UltiMed {
    Ort::Env env{ORT_LOGGING_LEVEL_ERROR, "NoteVive"};
    Ort::MemoryInfo memory{Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault)};
    Ort::Session preprocessor{nullptr}, encoder{nullptr}, decoder{nullptr};
    std::vector<std::string> vocab;
    notevive::LexicalContext lexical;

    template<class T, size_t N>
    Ort::Value input(T *data, size_t count, const std::array<int64_t, N> &shape) {
        return Ort::Value::CreateTensor<T>(memory, data, count, shape.data(), shape.size());
    }

public:
    explicit UltiMed(const std::filesystem::path &directory)
        : vocab(loadVocab(directory / "vocab.txt")), lexical(vocab) {
        env.DisableTelemetryEvents();
        require(std::string(Ort::GetVersionString()) == "1.32.0");
        auto opts = options();
        preprocessor = Ort::Session(env, (directory / "nemo128.onnx").c_str(), opts);
        encoder = Ort::Session(env, (directory / "encoder-model.int8.onnx").c_str(), opts);
        decoder = Ort::Session(env, (directory / "decoder_joint-model.int8.onnx").c_str(), opts);
    }

    int setPhrases(const char *terms) {
        if (!terms) return lexical.set({});
        const size_t length = ::strnlen(terms, lexical.maxInputBytes + 1);
        return lexical.set({terms, length});
    }

    std::string decode(const float *samples, int32_t sampleCount) {
        int64_t signalLength = sampleCount;
        std::vector<float> waveform(samples, samples + sampleCount);
        // The exported reflect padding needs more than 256 input samples.
        // A shorter, forced Stop may supply a sliver of audio; do not decode it.
        if (waveform.size() <= 256) return "";
        const std::array<int64_t, 1> scalarShape{1};
        const std::array<int64_t, 2> waveformShape{1, signalLength};
        std::array<Ort::Value, 2> waveIn{
            input(waveform.data(), waveform.size(), waveformShape), input(&signalLength, 1, scalarShape)
        };
        const char *waveInputNames[]{"waveforms", "waveforms_lens"};
        const char *waveOutputNames[]{"features", "features_lens"};
        const Ort::RunOptions run;
        auto features = preprocessor.Run(run, waveInputNames, waveIn.data(), waveIn.size(), waveOutputNames, 2);
        auto featureShape = features[0].GetTensorTypeAndShapeInfo().GetShape();
        require(featureShape.size() == 3 && featureShape[0] == 1 && featureShape[1] == kFeatures);
        const char *encodeInputNames[]{"audio_signal", "length"};
        const char *encodeOutputNames[]{"outputs", "encoded_lengths"};
        auto enc = encoder.Run(run, encodeInputNames, features.data(), features.size(), encodeOutputNames, 2);
        const auto encShape = enc[0].GetTensorTypeAndShapeInfo().GetShape();
        require(encShape.size() == 3 && encShape[0] == 1 && encShape[1] == kEncoderSize);
        require(enc[1].GetTensorTypeAndShapeInfo().GetElementCount() == 1);
        const auto stepCount = enc[1].GetTensorData<int64_t>()[0];
        require(stepCount >= 0 && stepCount <= encShape[2]);
        const auto *encData = enc[0].GetTensorData<float>();

        bool changed = false;
        std::string candidate = transcribe(encData, encShape[2], stepCount, lexical.enabled(), changed);
        if (!changed) return candidate;
        // Replay only the comparatively cheap prediction network if a lexical
        // score actually changed a token; share the unchanged acoustic features.
        bool unused = false;
        std::string original = transcribe(encData, encShape[2], stepCount, false, unused);
        return lexical.permits(original, candidate) ? candidate : original;
    }

private:
    std::string transcribe(const float *encData, int64_t frameCount, int64_t stepCount,
                           bool hinted, bool &changed) {
        const Ort::RunOptions run;
        const std::array<int64_t, 1> scalarShape{1};
        std::array<float, kEncoderSize> frame{};
        std::array<float, 2 * kStateWidth> zeros1{}, zeros2{};
        const std::array<int64_t, 3> frameShape{1, kEncoderSize, 1};
        const std::array<int64_t, 3> stateShape{2, 1, kStateWidth};
        const std::array<int64_t, 2> tokenShape{1, 1};
        int32_t previousToken = kBlank;
        int32_t tokenLength = 1;
        std::array<Ort::Value, 5> decodeIn{
            input(frame.data(), frame.size(), frameShape),
            input(&previousToken, 1, tokenShape),
            input(&tokenLength, 1, scalarShape),
            input(zeros1.data(), zeros1.size(), stateShape),
            input(zeros2.data(), zeros2.size(), stateShape)
        };
        const char *decodeInputNames[]{
            "encoder_outputs", "targets", "target_length", "input_states_1", "input_states_2"
        };
        const char *decodeOutputNames[]{"outputs", "output_states_1", "output_states_2"};
        std::string text;
        int64_t lastFrame = -1;
        int emittedAtFrame = 0;
        size_t hintPrefix = notevive::LexicalContext::none;
        for (int64_t t = 0; t < stepCount;) {
            if (t != lastFrame) {
                for (int64_t i = 0; i < kEncoderSize; ++i) frame[i] = encData[i * frameCount + t];
                lastFrame = t;
            }
            auto out = decoder.Run(run, decodeInputNames, decodeIn.data(), decodeIn.size(), decodeOutputNames, 3);
            require(out[0].GetTensorTypeAndShapeInfo().GetElementCount() == kVocab + kDurationBins);
            const auto *logits = out[0].GetTensorData<float>();
            const auto rawToken = static_cast<int32_t>(std::max_element(logits, logits + kVocab) - logits);
            const auto token = hinted ? lexical.suggest(hintPrefix, rawToken, logits, kBlank, text.empty(), true)
                                      : rawToken;
            changed |= token != rawToken;
            const auto duration = std::max_element(logits + kVocab, logits + kVocab + kDurationBins)
                - (logits + kVocab);
            require(std::isfinite(logits[token]) && std::isfinite(logits[kVocab + duration]));
            if (token != kBlank) {
                if (hinted) hintPrefix = lexical.advance(hintPrefix, token, text.empty(), true);
                text += vocab[token];
                previousToken = token;
                decodeIn[3] = std::move(out[1]);
                decodeIn[4] = std::move(out[2]);
                ++emittedAtFrame;
            }
            if (duration > 0 || token == kBlank || emittedAtFrame == kMaximumTokensPerFrame) {
                t += std::max<decltype(duration)>(1, duration);
                emittedAtFrame = 0;
            }
        }
        // The source vocabulary uses U+2581 for spaces. Normalise resulting
        // ASCII whitespace only, without changing words, values, or punctuation.
        std::string result;
        bool space = false;
        for (auto ch : text) {
            if (ch == ' ' || ch == '\r' || ch == '\n' || ch == '\t') {
                space = !result.empty();
            } else {
                if (space) result += ' ';
                result += ch;
                space = false;
            }
        }
        return result;
    }
};
} // namespace

extern "C" void *NVUltiMedCreate(const char *model_directory) {
    if (!model_directory || !*model_directory) return nullptr;
    try { return new UltiMed(model_directory); }
    catch (...) { return nullptr; }
}

extern "C" int NVUltiMedSetPhrases(void *handle, const char *terms) {
    if (!handle) return -1;
    try { return static_cast<UltiMed *>(handle)->setPhrases(terms); }
    catch (...) { return -1; }
}

extern "C" int NVUltiMedDecode(void *handle, const float *samples, int32_t sample_count, char **out_text) {
    if (!out_text) return 1;
    *out_text = nullptr;
    if (!handle || !samples || sample_count <= 0 || sample_count > kMaximumSamples) return 1;
    try {
        auto text = static_cast<UltiMed *>(handle)->decode(samples, sample_count);
        *out_text = ::strdup(text.c_str());
        return *out_text ? 0 : 1;
    } catch (...) { return 1; }
}

extern "C" void NVUltiMedFreeText(char *text) { std::free(text); }
extern "C" void NVUltiMedDestroy(void *handle) { delete static_cast<UltiMed *>(handle); }
