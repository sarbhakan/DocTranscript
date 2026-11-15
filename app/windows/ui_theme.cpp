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

HFONT make_ui_font(HDC dc, int height, int weight) {
    LOGFONTW font{};
    font.lfHeight = height;
    font.lfWeight = weight;
    font.lfCharSet = DEFAULT_CHARSET;
    font.lfPitchAndFamily = VARIABLE_PITCH | FF_SWISS;
    font.lfQuality = DEFAULT_QUALITY; // Respect the display's text smoothing.
    const auto try_face = [&](const wchar_t* face) -> HFONT {
        std::wmemset(font.lfFaceName, 0, LF_FACESIZE);
        std::wmemcpy(font.lfFaceName, face, std::wcslen(face));
        const auto candidate = CreateFontIndirectW(&font);
        if (!candidate || !dc) return candidate;
        const auto previous = SelectObject(dc, candidate);
        wchar_t mapped[LF_FACESIZE]{};
        const bool selected = previous && previous != HGDI_ERROR;
        const bool known = selected && GetTextFaceW(dc, LF_FACESIZE, mapped);
        if (selected) SelectObject(dc, previous);
        if (known && CompareStringOrdinal(mapped, -1, face, -1, TRUE) == CSTR_EQUAL)
            return candidate;
        DeleteObject(candidate);
        return nullptr;
    };
    if (weight == FW_SEMIBOLD) {
        // Segoe UI exposes a named Semibold face on Windows. Ask for it
        // directly before falling back to weight matching in the family.
        if (const auto semibold = try_face(L"Segoe UI Semibold")) return semibold;
    }
    if (const auto segoe = try_face(L"Segoe UI")) return segoe;
    if (const auto arial = try_face(L"Arial")) return arial;
    font.lfFaceName[0] = L'\0'; // Let GDI match the requested sans-serif family.
    return CreateFontIndirectW(&font);
}

} // namespace

Layout layout(int width, int height, UINT dpi, bool separate_passage, bool hidden) {
    if (!dpi) dpi = 96;
    const auto px = [dpi](int value) { return scale(value, dpi); };
    Layout out;
    const auto put = [&](Slot slot, int x, int y, int w, int h) {
        // Work areas can be smaller than the requested minimum at high DPI.
        const int left = std::clamp(x, 0, width);
        const int top = std::clamp(y, 0, height);
        out.slots[at(slot)] = {left, top, std::clamp(x + w, left, width), std::clamp(y + h, top, height)};
    };
    width = std::max(0, width);
    height = std::max(0, height);
    const bool compact = width < px(810) || height < px(540);
    const int pad = px(compact ? 12 : 20);
    const int right = width - pad, usable = std::max(0, right - pad);
    const int actions_w = px(104);
    const bool show_badge = usable >= px(600);
    const int brand_width = usable - actions_w - px(show_badge ? 185 : 10);
    put(Slot::brand, pad, px(11), brand_width, px(34));
    put(Slot::subtitle, pad, px(43), brand_width, px(19));
    put(Slot::actions, right - actions_w, px(18), actions_w, px(34));
    if (show_badge)
        put(Slot::badge, right - actions_w - px(172), px(20), px(152), px(28));

    const int card_top = px(compact ? 67 : 72), card_bottom = std::max(card_top, height - px(31));
    if (hidden) {
        put(Slot::masked_info, pad + px(14), card_top + px(14), usable - px(28), px(46));
        put(Slot::microphone, pad + px(30), card_top + px(72), usable - px(44), px(45));
        return out;
    }
    const int gap = px(compact ? 8 : 12), inset = px(compact ? 10 : 15);
    const int side = std::min(std::clamp(usable * 31 / 100, px(218), px(328)), usable * 45 / 100);
    const int left = pad + inset, left_w = side - 2 * inset;
    const int card_x = pad + side + gap, inner_x = card_x + inset, inner_right = right - inset;
    const int inner_w = inner_right - inner_x;
    put(Slot::library_card, pad, card_top, side, card_bottom - card_top);
    put(Slot::note_card, card_x, card_top, right - card_x, card_bottom - card_top);

    int row = card_top + inset;
    put(Slot::new_note, left, row, left_w, px(34));
    row += px(44);
    put(Slot::search_label, left, row, left_w, px(17));
    put(Slot::search, left, row + px(18), left_w, px(28));
    row += px(56);
    put(Slot::folders_label, left, row, left_w, px(18));
    row += px(20);
    const int tree_budget = card_bottom - inset - row - px(78);
    const int folder_h = std::max(0, std::min(tree_budget,
        std::clamp((card_bottom - card_top) / 4, px(43), px(147))));
    put(Slot::folder_tree, left, row, left_w, folder_h);
    row += folder_h + px(11);
    put(Slot::library_label, left, row, left_w, px(18));
    put(Slot::library, left, row + px(20), left_w, card_bottom - inset - row - px(20));

    row = card_top + inset;
    put(Slot::title_label, inner_x, row, inner_w, px(17));
    put(Slot::title, inner_x, row + px(18), inner_w, px(34));
    put(Slot::note_info, inner_x, row + px(58), inner_w, px(17));
    put(Slot::note_dates, inner_x, row + px(76), inner_w, px(18));
    put(Slot::body_label, inner_x, row + px(101), inner_w, px(18));
    const int dock = std::max(row + px(155), card_bottom - inset - px(83));
    const int editor_top = row + px(120);
    int editor_bottom = dock - px(10);
    if (separate_passage) {
        // Keep the microphone controls fixed; reserve room for the only
        // visible copy of a rejected passage even on a short work area.
        const int passage_h = std::clamp((editor_bottom - editor_top - px(25)) / 2, px(24), px(62));
        put(Slot::draft, inner_x, editor_bottom - passage_h, inner_w, passage_h);
        put(Slot::draft_label, inner_x, editor_bottom - passage_h - px(22), inner_w, px(18));
        editor_bottom -= passage_h + px(30);
    }
    put(Slot::body, inner_x, editor_top, inner_w, editor_bottom - editor_top);
    const int dict_w = std::min(px(153), std::max(0, inner_w - px(88)));
    put(Slot::dictate, inner_x, dock, dict_w, px(36));
    put(Slot::copy, inner_x + dict_w + px(8), dock, std::min(px(101), inner_w - dict_w - px(8)), px(36));
    put(Slot::microphone, inner_x + px(18), dock + px(44), inner_w - px(18), px(38));
    put(Slot::storage, pad + px(4), card_bottom + px(5), usable - px(8), px(22));
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
    const HDC dc = GetDC(nullptr);
    for (std::size_t i = 0; i != fonts_.size(); ++i) {
        if (const auto next = make_ui_font(dc, -scale(sizes[i], dpi_), weights[i])) {
            previous_fonts_[i] = fonts_[i];
            fonts_[i] = next;
        }
    }
    if (dc) ReleaseDC(nullptr, dc);
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
    if (badge.right > badge.left) {
        InflateRect(&badge, px(7), px(4));
        rounded(dc, badge, px(21), contrast_ ? paper : hint, line);
    }
    const auto status = bounds[Slot::microphone];
    const COLORREF dot = contrast_ ? GetSysColor(COLOR_WINDOWTEXT) :
        mic == Mic::recording || mic == Mic::error ? recording :
        mic == Mic::pending || mic == Mic::preparing ? amber : accent;
    RECT indicator{status.left - px(16), status.top + px(4), status.left - px(8), status.top + px(12)};
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
        // Keep HASLINES/LINESATROOT for the native root expander. Hide the
        // dotted connectors, without changing hierarchy, indentation or keys.
        TreeView_SetLineColor(folders, contrast_ ? CLR_DEFAULT : card);
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
