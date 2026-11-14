#include "ui_theme.h"
#include <algorithm>
#include <cwchar>
#include <iterator>

namespace doct::ui {
namespace {

constexpr COLORREF canvas = RGB(242, 247, 246);
constexpr COLORREF card = RGB(255, 255, 255);
constexpr COLORREF hint = RGB(238, 247, 244);
constexpr COLORREF outline = RGB(206, 221, 217);
constexpr COLORREF text = RGB(17, 40, 45);
constexpr COLORREF muted = RGB(63, 89, 95);
constexpr COLORREF accent = RGB(0, 103, 94);
constexpr COLORREF accent_hover = RGB(0, 87, 79);
constexpr COLORREF accent_down = RGB(0, 69, 64);
constexpr COLORREF recording = RGB(158, 39, 59);
constexpr COLORREF recording_hover = RGB(136, 31, 49);
constexpr COLORREF recording_down = RGB(111, 23, 39);
constexpr COLORREF amber = RGB(143, 81, 16);

int scale(int value, UINT dpi) { return MulDiv(value, static_cast<int>(dpi), 96); }

template <class Enum>
constexpr std::size_t at(Enum item) { return static_cast<std::size_t>(item); }

HBRUSH solid_dc(HDC dc, COLORREF color) {
    SetDCBrushColor(dc, color);
    return static_cast<HBRUSH>(GetStockObject(DC_BRUSH));
}

void rounded(HDC dc, const RECT& rc, int corner, COLORREF fill, COLORREF edge) {
    if (rc.right <= rc.left || rc.bottom <= rc.top) return;
    const int restore = SaveDC(dc);
    if (!restore) return;
    SelectObject(dc, solid_dc(dc, fill));
    SelectObject(dc, GetStockObject(DC_PEN));
    SetDCPenColor(dc, edge);
    RoundRect(dc, rc.left, rc.top, rc.right, rc.bottom, corner, corner);
    RestoreDC(dc, restore);
}

} // namespace

Layout layout(int width, int height, UINT dpi, bool copy_button, bool external_button) {
    if (!dpi) dpi = 96;
    const auto px = [dpi](int value) { return scale(value, dpi); };
    Layout out;
    const auto put = [&](Slot slot, int x, int y, int w, int h) {
        out.slots[at(slot)] = {x, y, x + std::max(w, 0), y + std::max(h, 0)};
    };
    const int pad = px(20), right = width - pad, usable = std::max(0, right - pad);
    const bool compact = width < px(850) || height < px(600);
    const bool tight = height < px(540);
    const int brand_width = std::max(0, usable - px(213));
    put(Slot::brand, pad, px(tight ? 6 : 12), brand_width, px(35));
    put(Slot::subtitle, pad, px(tight ? 38 : 46), brand_width, px(21));
    put(Slot::badge, right - px(193), px(tight ? 13 : 21), px(193), px(27));

    int x = pad, y = px(tight ? 63 : compact ? 71 : 77);
    auto action = [&](Slot slot, int w) {
        if (x > pad && x + px(w) > right) { x = pad; y += px(compact ? 39 : 43); }
        put(slot, x, y, std::min(usable, px(w)), px(compact ? 33 : 36));
        x += px(w + 8);
    };
    action(Slot::dictate, 160);
    action(Slot::save, 108);
    if (copy_button) action(Slot::copy, 123);
    action(Slot::privacy, 136);
    action(Slot::vocabulary, 106);
    if (external_button) action(Slot::external, 135);

    const int status_y = y + px(compact ? 40 : 46);
    // Two lines at compact widths, including the last known external target.
    put(Slot::microphone, pad + px(27), status_y + px(5), usable - px(39), px(39));
    const int card_top = status_y + px(55), card_bottom = std::max(card_top, height - px(tight ? 31 : 40));
    const int gap = px(12), inset = px(tight ? 9 : 12);
    const int side = std::min(std::clamp(usable * 33 / 100, px(230), px(350)), usable);
    const int left = pad + inset, left_width = std::max(0, side - 2 * inset);
    const int card_x = pad + side + gap, inner_x = card_x + inset, inner_right = right - inset;
    const int inner_width = std::max(0, inner_right - inner_x);
    put(Slot::library_card, pad, card_top, side, card_bottom - card_top);
    put(Slot::note_card, card_x, card_top, right - card_x, card_bottom - card_top);

    int row = card_top + inset;
    const int folder_btn = px(82), split = px(6);
    put(Slot::new_note, left, row, left_width - folder_btn - split, px(32));
    put(Slot::new_folder, left + left_width - folder_btn, row, folder_btn, px(32));
    row += px(tight ? 33 : compact ? 37 : 39);
    put(Slot::folders_label, left, row + px(3), left_width - px(89), px(20));
    put(Slot::folder_actions, left + left_width - px(83), row, px(83), px(25));
    row += px(tight ? 26 : compact ? 27 : 29);
    const int tree_budget = card_bottom - 2 * inset - row - px(tight ? 92 : 101) - px(19) - px(7) - px(40);
    const int folder_h = std::clamp(std::min((card_bottom - card_top - px(157)) / 3, tree_budget),
        px(tight ? 32 : 38), px(164));
    put(Slot::folder_tree, left, row, left_width, folder_h);
    row += folder_h + px(7);
    put(Slot::search_label, left, row, left_width, px(18));
    put(Slot::search, left, row + px(18), left_width, px(tight ? 24 : 27));
    put(Slot::search_all, left, row + px(tight ? 44 : 48), left_width, px(19));
    put(Slot::sort, left, row + px(tight ? 64 : 70), left_width, px(140)); // Native combo dropdown height.
    row += px(tight ? 92 : 101);
    put(Slot::library_label, left, row, left_width, px(18));
    put(Slot::library, left, row + px(19), left_width, card_bottom - inset - row - px(19));

    row = card_top + inset;
    const int action_w = px(93);
    put(Slot::title_label, inner_x, row, inner_width, px(17));
    put(Slot::title, inner_x, row + px(18), inner_width - action_w - split, px(35));
    put(Slot::move_note, inner_right - action_w, row + px(18), action_w, px(35));
    put(Slot::note_info, inner_x, row + px(57), inner_width, px(18));
    put(Slot::note_dates, inner_x, row + px(76), inner_width, px(18));
    put(Slot::body_label, inner_x, row + px(99), inner_width, px(18));
    const int draft_height = std::clamp((card_bottom - card_top) / 7, px(37), px(70));
    const int draft_y = card_bottom - inset - draft_height;
    put(Slot::body, inner_x, row + px(118), inner_width, draft_y - row - px(147));
    put(Slot::draft_label, inner_x, draft_y - px(23), inner_width, px(20));
    put(Slot::draft, inner_x, draft_y, inner_width, draft_height);
    const int storage_y = card_bottom + px(tight ? 4 : 9);
    put(Slot::storage, pad + px(4), storage_y, usable - px(8), std::max(0, height - storage_y));
    put(Slot::masked_info, pad + px(15), card_top + px(15), usable - px(30), px(50));
    return out;
}

void place(HWND control, const RECT& bounds) {
    if (control) MoveWindow(control, bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top, TRUE);
}

Theme::~Theme() {
    release_previous_fonts();
    for (const auto value : fonts_) if (value) DeleteObject(value);
    for (const auto value : brushes_) if (value) DeleteObject(value);
}

void Theme::release_previous_fonts() {
    for (auto& value : previous_fonts_) {
        if (value) DeleteObject(value);
        value = nullptr;
    }
}

void Theme::refresh(UINT dpi) {
    dpi_ = dpi ? dpi : 96;
    HIGHCONTRASTW contrast{sizeof(contrast), 0, nullptr};
    contrast_ = !SystemParametersInfoW(SPI_GETHIGHCONTRAST, sizeof(contrast), &contrast, 0) ||
        (contrast.dwFlags & HCF_HIGHCONTRASTON) != 0;
    constexpr std::array<int, at(Font::count)> sizes{15, 29, 15, 21, 13, 14};
    constexpr std::array<int, at(Font::count)> weights{FW_NORMAL, FW_SEMIBOLD, FW_SEMIBOLD, FW_SEMIBOLD, FW_NORMAL, FW_SEMIBOLD};
    for (std::size_t i = 0; i != fonts_.size(); ++i) {
        LOGFONTW font{};
        font.lfHeight = -scale(sizes[i], dpi_);
        font.lfWeight = weights[i];
        font.lfCharSet = DEFAULT_CHARSET;
        font.lfQuality = CLEARTYPE_QUALITY;
        constexpr wchar_t face[] = L"Segoe UI";
        std::copy(std::begin(face), std::end(face), std::begin(font.lfFaceName));
        if (const auto next = CreateFontIndirectW(&font)) {
            previous_fonts_[i] = fonts_[i];
            fonts_[i] = next;
        }
    }
    constexpr std::array<COLORREF, at(Surface::count)> fills{canvas, card, card, hint};
    for (std::size_t i = 0; i != brushes_.size(); ++i) {
        if (!brushes_[i]) brushes_[i] = CreateSolidBrush(fills[i]);
    }
}

HFONT Theme::font(Font role) const {
    const auto selected = fonts_[at(role)];
    return selected ? selected : static_cast<HFONT>(GetStockObject(DEFAULT_GUI_FONT));
}

HBRUSH Theme::colors(HDC dc, HWND control, Surface surface, Ink ink) const {
    const bool enabled = !control || IsWindowEnabled(control);
    if (contrast_) {
        const int background = surface == Surface::canvas ? COLOR_BTNFACE : COLOR_WINDOW;
        SetTextColor(dc, GetSysColor(!enabled ? COLOR_GRAYTEXT : surface == Surface::canvas ? COLOR_BTNTEXT : COLOR_WINDOWTEXT));
        SetBkColor(dc, GetSysColor(background));
        return GetSysColorBrush(background);
    }
    const auto brush = brushes_[at(surface)];
    const COLORREF background = surface == Surface::canvas ? canvas : surface == Surface::hint ? hint : card;
    SetBkColor(dc, background);
    SetTextColor(dc, !enabled || ink == Ink::muted ? muted : ink == Ink::accent ? accent : text);
    return brush ? brush : solid_dc(dc, background);
}

void Theme::paint(HWND window, const Layout& bounds, bool hidden, Mic mic) const {
    PAINTSTRUCT paint{};
    const HDC dc = BeginPaint(window, &paint);
    if (dc) draw_background(dc, paint.rcPaint, bounds, hidden, mic);
    EndPaint(window, &paint);
}

void Theme::draw_background(HDC dc, const RECT& clip, const Layout& bounds, bool hidden, Mic mic) const {
    const int restore = SaveDC(dc);
    if (!restore) return;
    const auto px = [this](int n) { return scale(n, dpi_); };
    FillRect(dc, &clip, contrast_ ? GetSysColorBrush(COLOR_BTNFACE) : solid_dc(dc, canvas));
    const auto paper = contrast_ ? GetSysColor(COLOR_WINDOW) : card;
    const auto line = contrast_ ? GetSysColor(COLOR_WINDOWTEXT) : outline;
    if (!hidden) {
        rounded(dc, bounds[Slot::library_card], px(17), paper, line);
        rounded(dc, bounds[Slot::note_card], px(17), paper, line);
        for (const Slot slot : {Slot::folder_tree, Slot::search, Slot::library, Slot::title, Slot::body, Slot::draft}) {
            auto frame = bounds[slot];
            if (frame.right <= frame.left || frame.bottom <= frame.top) continue;
            InflateRect(&frame, px(1), px(1));
            const auto edge = contrast_ ? GetSysColorBrush(COLOR_WINDOWTEXT) : solid_dc(dc, outline);
            FrameRect(dc, &frame, edge);
        }
    }
    auto badge = bounds[Slot::badge];
    InflateRect(&badge, px(7), px(4));
    rounded(dc, badge, px(21), contrast_ ? paper : hint, line);
    auto status = bounds[Slot::microphone];
    status.left -= px(27); status.right += px(12);
    status.top -= px(5); status.bottom += px(5);
    rounded(dc, status, px(14), paper, line);
    const COLORREF dot = contrast_ ? GetSysColor(COLOR_WINDOWTEXT) :
        mic == Mic::recording || mic == Mic::error ? recording :
        mic == Mic::pending || mic == Mic::preparing ? amber : accent;
    RECT indicator{status.left + px(11), status.top + px(12), status.left + px(19), status.top + px(20)};
    rounded(dc, indicator, px(8), dot, dot);
    if (hidden) {
        auto obscured = bounds[Slot::masked_info];
        InflateRect(&obscured, px(15), px(15));
        rounded(dc, obscured, px(14), paper, line);
    }
    RestoreDC(dc, restore);
}

bool Theme::draw_button(const NMCUSTOMDRAW& draw, Button role, bool on_card) const {
    if (contrast_ || draw.dwDrawStage != CDDS_PREPAINT) return false;
    const int restore = SaveDC(draw.hdc);
    if (!restore) return false;
    const auto px = [this](int value) { return scale(value, dpi_); };
    const bool disabled = (draw.uItemState & CDIS_DISABLED) != 0 || !IsWindowEnabled(draw.hdr.hwndFrom);
    const bool down = (draw.uItemState & CDIS_SELECTED) != 0;
    const bool hover = (draw.uItemState & CDIS_HOT) != 0;
    const bool strong = role != Button::secondary && !disabled;
    COLORREF fill;
    if (disabled) fill = RGB(228, 237, 234);
    else if (role == Button::primary) fill = down ? accent_down : hover ? accent_hover : accent;
    else if (role == Button::recording) fill = down ? recording_down : hover ? recording_hover : recording;
    else fill = down ? RGB(222, 237, 232) : hover ? hint : card;
    FillRect(draw.hdc, &draw.rc, solid_dc(draw.hdc, on_card ? card : canvas));
    rounded(draw.hdc, draw.rc, px(12), fill, strong ? fill : outline);
    RECT label = draw.rc;
    InflateRect(&label, -px(7), 0);
    SetBkMode(draw.hdc, TRANSPARENT);
    SetTextColor(draw.hdc, disabled ? muted : strong ? card : text);
    SelectObject(draw.hdc, font(Font::button));
    wchar_t name[128]{};
    GetWindowTextW(draw.hdr.hwndFrom, name, static_cast<int>(std::size(name)));
    const LRESULT cues = SendMessageW(draw.hdr.hwndFrom, WM_QUERYUISTATE, 0, 0);
    DrawTextW(draw.hdc, name, -1, &label, DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS |
        ((cues & UISF_HIDEACCEL) ? DT_HIDEPREFIX : 0));
    if ((draw.uItemState & CDIS_FOCUS) != 0 || GetFocus() == draw.hdr.hwndFrom) {
        RECT focused = draw.rc;
        InflateRect(&focused, -px(3), -px(3));
        SetTextColor(draw.hdc, strong ? card : text);
        SetBkColor(draw.hdc, fill);
        DrawFocusRect(draw.hdc, &focused);
    }
    RestoreDC(draw.hdc, restore);
    return true;
}

void Theme::draw_note_row(const DRAWITEMSTRUCT& draw, std::wstring_view item) const {
    const int restore = SaveDC(draw.hDC);
    if (!restore) return;
    const auto px = [this](int n) { return scale(n, dpi_); };
    const bool selected = (draw.itemState & ODS_SELECTED) != 0;
    const bool focused = (draw.itemState & ODS_FOCUS) != 0;
    const auto paper = contrast_ ? GetSysColor(COLOR_WINDOW) : card;
    const auto line = contrast_ ? GetSysColor(COLOR_WINDOWTEXT) : outline;
    FillRect(draw.hDC, &draw.rcItem, solid_dc(draw.hDC, paper));
    RECT row = draw.rcItem;
    InflateRect(&row, -px(4), -px(2));
    if (row.right <= row.left || row.bottom <= row.top) { RestoreDC(draw.hDC, restore); return; }
    if (selected) {
        const auto background = contrast_ ? GetSysColor(COLOR_HIGHLIGHT) : RGB(222, 239, 233);
        rounded(draw.hDC, row, px(8), background, background);
        RECT bar{row.left + px(1), row.top + px(6), row.left + px(4), row.bottom - px(6)};
        const auto marker = contrast_ ? GetSysColor(COLOR_HIGHLIGHTTEXT) : accent;
        rounded(draw.hDC, bar, px(3), marker, marker);
    }
    const bool disabled = (draw.itemState & ODS_DISABLED) != 0 || !IsWindowEnabled(draw.hwndItem);
    const auto tone = contrast_ ? GetSysColor(selected ? COLOR_HIGHLIGHTTEXT : disabled ? COLOR_GRAYTEXT : COLOR_WINDOWTEXT)
                                : disabled ? muted : text;
    const auto separator = item.rfind(L" · ");
    const auto title = item.substr(0, separator);
    const auto date = separator == std::wstring_view::npos ? std::wstring_view{} : item.substr(separator + 3);
    SetBkMode(draw.hDC, TRANSPARENT);
    RECT line_box{row.left + px(10), row.top + px(3), row.right - px(5), row.top + px(22)};
    SelectObject(draw.hDC, font(Font::heading));
    SetTextColor(draw.hDC, tone);
    if (!title.empty()) DrawTextW(draw.hDC, title.data(), static_cast<int>(title.size()), &line_box,
                                  DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX);
    if (!date.empty()) {
        line_box.top = row.top + px(21);
        line_box.bottom = row.bottom - px(2);
        SelectObject(draw.hDC, font(Font::small));
        SetTextColor(draw.hDC, contrast_ ? tone : muted);
        DrawTextW(draw.hDC, date.data(), static_cast<int>(date.size()), &line_box,
                  DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX);
    }
    if (focused) {
        SetTextColor(draw.hDC, contrast_ ? tone : text);
        SetBkColor(draw.hDC, contrast_ && selected ? GetSysColor(COLOR_HIGHLIGHT) : paper);
        DrawFocusRect(draw.hDC, &row);
    } else if (!selected) {
        RECT divider{row.left + px(8), row.bottom - 1, row.right - px(5), row.bottom};
        FillRect(draw.hDC, &divider, solid_dc(draw.hDC, line));
    }
    RestoreDC(draw.hDC, restore);
}

void Theme::style_collections(HWND folders, HWND notes) const {
    if (folders) {
        TreeView_SetBkColor(folders, contrast_ ? static_cast<COLORREF>(-1) : card);
        TreeView_SetTextColor(folders, contrast_ ? static_cast<COLORREF>(-1) : text);
        TreeView_SetItemHeight(folders, static_cast<SHORT>(scale(22, dpi_)));
    }
    if (notes) SendMessageW(notes, LB_SETITEMHEIGHT, 0, scale(40, dpi_));
}

void Theme::inset_editor(HWND editor) const {
    if (!editor) return;
    RECT box{};
    GetClientRect(editor, &box);
    const auto x = scale(10, dpi_), y = scale(7, dpi_);
    if (box.right <= 2 * x || box.bottom <= 2 * y) return;
    InflateRect(&box, -x, -y);
    SendMessageW(editor, EM_SETRECT, 0, reinterpret_cast<LPARAM>(&box));
}

} // namespace doct::ui
