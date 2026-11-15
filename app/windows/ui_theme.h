#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <commctrl.h>
#include <array>
#include <cstddef>
#include <string_view>

namespace doct::ui {

enum class Slot : std::size_t {
    brand, subtitle, badge, dictate, save, copy, privacy, vocabulary, external, microphone,
    library_card, note_card, new_note, new_folder, folders_label, folder_actions, folder_tree,
    search_label, search, search_all, sort, library_label, library, title_label, title, move_note,
    note_info, note_dates, body_label, body, draft_label, draft, storage, masked_info, count
};

struct Layout {
    static constexpr int min_client_width = 690;
    static constexpr int min_client_height = 540;
    using Rects = std::array<RECT, static_cast<std::size_t>(Slot::count)>;
    Rects slots{};
    const RECT& operator[](Slot slot) const noexcept { return slots[static_cast<std::size_t>(slot)]; }
};

Layout layout(int width, int height, UINT dpi, bool copy_button, bool external_button);
void place(HWND control, const RECT& bounds);

enum class Font { body, brand, heading, note_title, small, button, count };
enum class Surface { canvas, card, paper, hint, count };
enum class Ink { normal, muted, accent };
enum class Button { primary, secondary, recording };
enum class Mic { ready, preparing, recording, pending, error };

class Theme {
public:
    Theme() = default;
    ~Theme();
    Theme(const Theme&) = delete;
    Theme& operator=(const Theme&) = delete;

    // Failed allocations retain the last usable font. Set the new fonts on all
    // children before releasing the previous fonts they were using.
    void refresh(UINT dpi);
    void release_previous_fonts();
    HFONT font(Font role = Font::body) const;
    HBRUSH colors(HDC dc, HWND control, Surface surface, Ink ink = Ink::normal) const;
    void paint(HWND window, const Layout& bounds, bool hidden, Mic mic) const;
    void draw_background(HDC dc, const RECT& clip, const Layout& bounds, bool hidden, Mic mic) const;
    // Return false to keep drawing in BUTTON's native implementation.
    bool draw_button(const NMCUSTOMDRAW& draw, Button role, bool on_card = false) const;
    void draw_note_row(const DRAWITEMSTRUCT& draw, std::wstring_view item) const;
    void style_collections(HWND folders, HWND notes) const;
    void inset_editor(HWND editor) const;

private:
    UINT dpi_ = 96;
    bool contrast_ = true; // Native system colors until settings are known.
    std::array<HFONT, static_cast<std::size_t>(Font::count)> fonts_{};
    decltype(fonts_) previous_fonts_{};
    std::array<HBRUSH, static_cast<std::size_t>(Surface::count)> brushes_{};
};

} // namespace doct::ui
