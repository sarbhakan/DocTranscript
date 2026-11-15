#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

namespace doct::ui {

enum class OverlayState { preparing, recording, finalizing, local, unavailable, uncertain };

// Display only a fixed status string; this object never takes draft text or a
// destination title. Call from the thread owning the application window.
class DictationOverlay {
public:
    DictationOverlay() = default;
    ~DictationOverlay();
    DictationOverlay(const DictationOverlay&) = delete;
    DictationOverlay& operator=(const DictationOverlay&) = delete;

    bool show(HWND app_window, HWND target_window, OverlayState state);
    void hide();

private:
    static LRESULT CALLBACK procedure(HWND window, UINT message, WPARAM wparam, LPARAM lparam);
    void arrange();
    void paint();
    HWND window_ = nullptr;
    HWND label_ = nullptr;
    HFONT font_ = nullptr;
    HMONITOR monitor_ = nullptr;
    UINT dpi_ = 96;
    OverlayState state_ = OverlayState::preparing;
};

} // namespace doct::ui
