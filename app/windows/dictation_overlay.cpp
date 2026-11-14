#include "dictation_overlay.h"
#include <algorithm>
#include <iterator>

namespace doct::ui {
namespace {

constexpr wchar_t WindowClass[] = L"NoteVive.DictationStatus";
constexpr UINT_PTR HideTimer = 1;
constexpr UINT KeepLocalVisibleMs = 4500;

const wchar_t* caption(OverlayState state) {
    switch (state) {
    case OverlayState::preparing: return L"NoteVive · Préparation…";
    case OverlayState::recording: return L"NoteVive · Micro ouvert";
    case OverlayState::finalizing: return L"NoteVive · Finalisation…";
    case OverlayState::local: return L"Conservé dans NoteVive";
    case OverlayState::unavailable: return L"Champ incompatible · Micro coupé";
    }
    return L"NoteVive";
}

int scale(int value, UINT dpi) { return MulDiv(value, static_cast<int>(dpi), 96); }

bool high_contrast() {
    HIGHCONTRASTW contrast{sizeof(contrast), 0, nullptr};
    return !SystemParametersInfoW(SPI_GETHIGHCONTRAST, sizeof(contrast), &contrast, 0) ||
        (contrast.dwFlags & HCF_HIGHCONTRASTON) != 0;
}

} // namespace

DictationOverlay::~DictationOverlay() {
    if (window_) DestroyWindow(window_);
    if (font_) DeleteObject(font_);
}

bool DictationOverlay::show(HWND app_window, HWND target_window, OverlayState state) {
    if (!IsWindow(app_window)) return false;
    const HWND anchor = IsWindow(target_window) ? target_window : app_window;
    monitor_ = MonitorFromWindow(anchor, MONITOR_DEFAULTTONEAREST);
    const UINT dpi = GetDpiForWindow(anchor);
    const int initial_dpi = dpi ? static_cast<int>(dpi) : 96;
    state_ = state;
    if (!window_) {
        const auto instance = reinterpret_cast<HINSTANCE>(GetWindowLongPtrW(app_window, GWLP_HINSTANCE));
        WNDCLASSEXW type{};
        type.cbSize = sizeof(type);
        type.hInstance = instance;
        type.lpfnWndProc = procedure;
        type.lpszClassName = WindowClass;
        if (!RegisterClassExW(&type) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) return false;
        MONITORINFO screen{sizeof(screen), {}, {}, 0};
        if (!GetMonitorInfoW(monitor_, &screen)) return false;
        // No owner: a minimized NoteVive must not minimize this status. The
        // instance explicitly destroys the window at application shutdown.
        if (!CreateWindowExW(WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_LAYERED,
            WindowClass, caption(state_), WS_POPUP | WS_BORDER | WS_CLIPCHILDREN,
            screen.rcWork.left, screen.rcWork.top, scale(285, initial_dpi), scale(46, initial_dpi),
            nullptr, nullptr, instance, this)) return false;
        // Desktop hit testing ignores a transparent layered window. Refuse
        // to claim that the indicator is visible if compositing failed.
        if (!SetLayeredWindowAttributes(window_, 0, 255, LWA_ALPHA)) {
            DestroyWindow(window_);
            return false;
        }
    }
    // Pass only fixed strings to native windows. The STATIC makes the status
    // available to accessibility tools even though the overlay takes no focus.
    SetWindowTextW(window_, caption(state_));
    SetWindowTextW(label_, caption(state_));
    arrange();
    KillTimer(window_, HideTimer);
    if ((state_ == OverlayState::local || state_ == OverlayState::unavailable) &&
            !SetTimer(window_, HideTimer, KeepLocalVisibleMs, nullptr)) {
        hide();
        return false;
    }
    InvalidateRect(window_, nullptr, FALSE);
    return IsWindowVisible(window_) != FALSE;
}

void DictationOverlay::hide() {
    if (!window_) return;
    KillTimer(window_, HideTimer);
    SetWindowPos(window_, nullptr, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER | SWP_HIDEWINDOW);
}

void DictationOverlay::arrange() {
    MONITORINFO screen{sizeof(screen), {}, {}, 0};
    if (!GetMonitorInfoW(monitor_, &screen)) return;
    // First move (without showing or activating) so PerMonitorV2 gives the
    // overlay its own actual DPI, even when the other application's HWND is
    // DPI-unaware. A WM_DPICHANGED from this call does not reenter arrange().
    if (MonitorFromWindow(window_, MONITOR_DEFAULTTONEAREST) != monitor_)
        SetWindowPos(window_, nullptr, screen.rcWork.left, screen.rcWork.top, 0, 0,
            SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER);
    const UINT reported = GetDpiForWindow(window_);
    const UINT dpi = reported ? reported : 96;
    if (!font_ || dpi_ != dpi) {
        dpi_ = dpi;
        LOGFONTW spec{};
        spec.lfHeight = -scale(16, dpi_);
        spec.lfWeight = FW_SEMIBOLD;
        constexpr wchar_t name[] = L"Segoe UI";
        std::copy(std::begin(name), std::end(name), std::begin(spec.lfFaceName));
        if (const auto next = CreateFontIndirectW(&spec)) {
            SendMessageW(label_, WM_SETFONT, reinterpret_cast<WPARAM>(next), TRUE);
            if (font_) DeleteObject(font_);
            font_ = next;
        }
    }
    const RECT& work = screen.rcWork;
    const int margin = scale(16, dpi_), width = std::min(scale(285, dpi_), static_cast<int>(work.right - work.left));
    const int height = std::min(scale(46, dpi_), static_cast<int>(work.bottom - work.top));
    SetWindowPos(window_, HWND_TOPMOST, std::max<int>(work.left, work.right - width - margin),
        std::max<int>(work.top, work.bottom - height - margin), width, height,
        SWP_NOACTIVATE | SWP_SHOWWINDOW);
    RECT rc{};
    GetClientRect(window_, &rc);
    const int left = scale(32, dpi_);
    MoveWindow(label_, left, 0, std::max<int>(0, rc.right - left - scale(8, dpi_)), rc.bottom, TRUE);
}

void DictationOverlay::paint() {
    PAINTSTRUCT update{};
    HDC dc = BeginPaint(window_, &update);
    const bool contrast = high_contrast();
    SetDCBrushColor(dc, RGB(244, 250, 247));
    FillRect(dc, &update.rcPaint, contrast ? GetSysColorBrush(COLOR_WINDOW) : static_cast<HBRUSH>(GetStockObject(DC_BRUSH)));
    RECT rc{};
    GetClientRect(window_, &rc);
    const int size = scale(9, dpi_), x = scale(13, dpi_), y = (rc.bottom - size) / 2;
    SetDCBrushColor(dc, contrast ? GetSysColor(COLOR_WINDOWTEXT) : state_ == OverlayState::recording ? RGB(158, 39, 59) : RGB(0, 103, 94));
    const auto brush = SelectObject(dc, GetStockObject(DC_BRUSH));
    const auto pen = SelectObject(dc, GetStockObject(NULL_PEN));
    Ellipse(dc, x, y, x + size, y + size);
    SelectObject(dc, pen);
    SelectObject(dc, brush);
    EndPaint(window_, &update);
}

LRESULT CALLBACK DictationOverlay::procedure(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    auto self = reinterpret_cast<DictationOverlay*>(GetWindowLongPtrW(window, GWLP_USERDATA));
    if (message == WM_NCCREATE) {
        self = static_cast<DictationOverlay*>(reinterpret_cast<const CREATESTRUCTW*>(lparam)->lpCreateParams);
        self->window_ = window;
        SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
    }
    if (!self) return DefWindowProcW(window, message, wparam, lparam);
    switch (message) {
    case WM_CREATE:
        self->label_ = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE | SS_NOPREFIX | SS_CENTERIMAGE,
            0, 0, 0, 0, window, nullptr, nullptr, nullptr);
        return self->label_ ? 0 : -1;
    case WM_PAINT: self->paint(); return 0;
    case WM_ERASEBKGND: return 1;
    case WM_CTLCOLORSTATIC: {
        const auto dc = reinterpret_cast<HDC>(wparam);
        const bool contrast = high_contrast();
        const auto bg = contrast ? GetSysColor(COLOR_WINDOW) : RGB(244, 250, 247);
        SetBkColor(dc, bg);
        SetTextColor(dc, contrast ? GetSysColor(COLOR_WINDOWTEXT) : RGB(17, 40, 45));
        SetDCBrushColor(dc, bg);
        return reinterpret_cast<LRESULT>(contrast ? GetSysColorBrush(COLOR_WINDOW) : GetStockObject(DC_BRUSH));
    }
    case WM_TIMER:
        if (wparam == HideTimer) { self->hide(); return 0; }
        break;
    case WM_MOUSEACTIVATE: return MA_NOACTIVATEANDEAT;
    case WM_NCHITTEST: return HTTRANSPARENT;
    case WM_DPICHANGED:
        // arrange() performs the final move using client geometry and monitor
        // work area. No focus-changing or DPI-triggered recursive position.
        return 0;
    case WM_SYSCOLORCHANGE:
    case WM_SETTINGCHANGE:
        RedrawWindow(window, nullptr, nullptr, RDW_INVALIDATE | RDW_ALLCHILDREN);
        break;
    case WM_NCDESTROY:
        self->window_ = self->label_ = nullptr;
        SetWindowLongPtrW(window, GWLP_USERDATA, 0);
        break;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

} // namespace doct::ui
