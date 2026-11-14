#ifndef NOTEVIVE_PAUSE_STATE_H
#define NOTEVIVE_PAUSE_STATE_H

#include "SileroPause.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <vector>

namespace notevive {

// Frame-based state with deterministic limits, separate from the model. Only
// qualified speech can be sent to ASR; bytes copied to ASR are not normalized,
// trimmed within a phrase, or changed by the VAD.
class PauseState {
public:
    static constexpr size_t hop = 512;
    static constexpr size_t hop_ms = 32;
    static constexpr size_t pause_frames = NV_SILERO_PAUSE_MS / hop_ms;
    static constexpr size_t preroll_frames = NV_SILERO_PREROLL_MS / hop_ms;
    static constexpr size_t max_samples = (NV_SILERO_MAX_SEGMENT_MS / hop_ms) * hop;
    static constexpr size_t min_voice_frames = 3;
    static constexpr float start_threshold = .5f;
    static constexpr float continue_threshold = .35f;

    explicit PauseState(size_t silence_ms = NV_SILERO_PAUSE_MS)
        : silence_frames_((silence_ms + hop_ms - 1) / hop_ms) { phrase_.reserve(max_samples); }

    void reset() {
        phrase_.clear();
        recent_start_ = recent_size_ = voice_ = quiet_ = 0;
        active_ = continuation_ = false;
    }

    int frame(const float *samples, size_t size, float probability, NVSileroEmit emit, void *context) {
        if (!active_) {
            if (probability < start_threshold) {
                remember(samples, size);
                return 0;
            }
            begin();
        }

        const bool voiced = probability >= continue_threshold;
        if (voiced) {
            ++voice_;
            quiet_ = 0;
        } else {
            ++quiet_;
        }

        phrase_.insert(phrase_.end(), samples, samples + size);
        // One noisy high-probability frame is not speech. Retain its waveform
        // in the pre-roll if real speech begins immediately afterwards.
        if (!qualified() && quiet_ >= min_voice_frames) {
            for (size_t pos = 0; pos < phrase_.size(); pos += hop) {
                remember(phrase_.data() + pos, std::min(hop, phrase_.size() - pos));
            }
            clear_phrase();
            return 0;
        }

        if (qualified() && quiet_ >= silence_frames_) {
            const int status = emit_phrase(emit, context);
            clear_phrase();
            return status;
        }
        if (phrase_.size() >= max_samples) {
            // Deterministic split for an unusually long unbroken utterance.
            // The next packet starts a new phrase without duplicating audio;
            // a short audible continuation is sufficient to emit its tail.
            const bool continues = qualified() && quiet_ < preroll_frames;
            if (!continues) {
                // If the forced boundary fell inside a quiet stretch, preserve
                // its most recent context for an eventual low-volume onset.
                const size_t recent = std::min(quiet_, preroll_frames) * hop;
                const size_t first = phrase_.size() - std::min(phrase_.size(), recent);
                for (size_t pos = first; pos < phrase_.size(); pos += hop) {
                    remember(phrase_.data() + pos, std::min(hop, phrase_.size() - pos));
                }
            }
            const int status = qualified() ? emit_phrase(emit, context) : 0;
            clear_phrase();
            active_ = continuation_ = continues;
            return status;
        }
        return 0;
    }

    int finish(NVSileroEmit emit, void *context) {
        const int status = qualified() ? emit_phrase(emit, context) : 0;
        reset();
        return status;
    }

private:
    struct HistoryFrame {
        std::array<float, hop> audio{};
        size_t size = 0;
    };
    std::array<HistoryFrame, preroll_frames> recent_{};
    std::vector<float> phrase_;
    size_t silence_frames_;
    size_t recent_start_ = 0, recent_size_ = 0, voice_ = 0, quiet_ = 0;
    bool active_ = false, continuation_ = false;

    bool qualified() const {
        return voice_ >= (continuation_ ? 1 : min_voice_frames);
    }

    void remember(const float *samples, size_t size) {
        const size_t slot = (recent_start_ + recent_size_) % recent_.size();
        std::copy_n(samples, size, recent_[slot].audio.begin());
        recent_[slot].size = size;
        if (recent_size_ < recent_.size()) ++recent_size_;
        else recent_start_ = (recent_start_ + 1) % recent_.size();
    }

    void begin() {
        for (size_t i = 0; i < recent_size_; ++i) {
            const auto &frame = recent_[(recent_start_ + i) % recent_.size()];
            phrase_.insert(phrase_.end(), frame.audio.begin(), frame.audio.begin() + frame.size);
        }
        recent_start_ = recent_size_ = 0;
        active_ = true;
    }

    void clear_phrase() {
        phrase_.clear();
        voice_ = quiet_ = 0;
        active_ = continuation_ = false;
    }

    int emit_phrase(NVSileroEmit emit, void *context) {
        return emit(context, phrase_.data(), phrase_.size()) == 0 ? 0 : -1;
    }
};

} // namespace notevive
#endif
