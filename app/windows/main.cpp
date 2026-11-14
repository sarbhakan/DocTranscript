#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <commctrl.h>
#include <wtsapi32.h>

#include <algorithm>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include <string>
#include <utility>
#include <vector>

#include "catalogue.h"
#include "engine.h"
#include "notes.h"

namespace {
constexpr wchar_t WindowClass[] = L"NoteVivePrototypeWindow";
constexpr UINT EngineMessage = WM_APP + 1;
constexpr UINT_PTR SaveTimer = 1;
constexpr UINT SaveDelayMs = 550;
constexpr UINT_PTR SearchTimer = 2;
constexpr UINT SearchDelayMs = 250;
constexpr std::size_t TitleLimit = notes::kMaxTitle;
constexpr std::size_t TextLimit = notes::kMaxText;
constexpr wchar_t OriginalEditProc[] = L"NoteVive.OriginalEditProc";

enum Control : int {
    New = 101, Dictate, Save, Privacy, Vocabulary, Library, Title, Body, Draft,
    FolderTree, SearchText, SearchAll, SortBy, NewFolder, FolderActions, MoveNote,
    RenameFolder, MoveFolder, RenameNote, NoteInfo,
};
enum class Phase { idle, preparing, listening, stopping, finalizing };

std::wstring runtime_path() {
    std::wstring path(32768, L'\0');
    const auto length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size()) return {};
    path.resize(length);
    auto slash = path.find_last_of(L"\\/");
    if (slash == std::wstring::npos) return {};
    path.resize(slash + 1);
    return path + L"runtime";
}

std::wstring get_text(HWND control) {
    const int length = GetWindowTextLengthW(control);
    std::wstring result(static_cast<std::size_t>(length) + 1, L'\0');
    const int actual = GetWindowTextW(control, result.data(), length + 1);
    result.resize(static_cast<std::size_t>(actual));
    return result;
}

// The multiline Win32 EDIT control expects CRLF line endings.
std::wstring editor_text(const std::wstring& source) {
    std::wstring result;
    result.reserve(source.size());
    for (std::size_t i = 0; i < source.size(); ++i) {
        const wchar_t ch = source[i];
        if (ch == L'\r' || ch == L'\n') {
            result += L"\r\n";
            if (ch == L'\r' && i + 1 < source.size() && source[i + 1] == L'\n') ++i;
        } else if (ch != L'\0') {
            result += ch;
        }
    }
    return result;
}

std::wstring display_title(const notes::Note& note) {
    if (note.title.find_first_not_of(L" \t\r\n") == std::wstring::npos) return L"Brouillon sans titre";
    return note.title;
}

std::wstring note_date(const std::wstring& date) {
    return date.size() >= 16
        ? date.substr(8, 2) + L"/" + date.substr(5, 2) + L"/" + date.substr(0, 4) + L" " + date.substr(11, 5)
        : date;
}

std::wstring list_caption(const notes::Note& note, notes::Sort order) {
    const auto date = note_date(order == notes::Sort::CreatedNewest ? note.created : note.modified);
    return date.empty() ? display_title(note) : display_title(note) + L" · " + date;
}

// Prototype notes stay within the local editor; don't create a clipboard item
// that Windows or a separate program could retain or synchronize.
LRESULT CALLBACK local_edit_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    const auto original = reinterpret_cast<WNDPROC>(GetPropW(window, OriginalEditProc));
    if (!original) return DefWindowProcW(window, message, wparam, lparam);
    if (message == WM_COPY || message == WM_CUT || message == WM_PASTE || message == WM_CONTEXTMENU) return 0;
    if (message == WM_CHAR && (wparam == 3 || wparam == 22 || wparam == 24)) return 0; // Ctrl+C/V/X.
    if (message == WM_KEYDOWN) {
        const bool ctrl = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        const bool shift = (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        if ((wparam == VK_INSERT && (ctrl || shift)) || (wparam == VK_DELETE && shift)) return 0;
    }
    if (message == WM_NCDESTROY) RemovePropW(window, OriginalEditProc);
    return CallWindowProcW(original, window, message, wparam, lparam);
}

bool restrict_clipboard(HWND edit) {
    const auto original = reinterpret_cast<HANDLE>(GetWindowLongPtrW(edit, GWLP_WNDPROC));
    if (!original || !SetPropW(edit, OriginalEditProc, original)) return false;
    if (!SetWindowLongPtrW(edit, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(local_edit_proc))) {
        RemovePropW(edit, OriginalEditProc);
        return false;
    }
    return true;
}

struct LibraryChoice {
    std::wstring label;
    std::wstring id;
};

struct LibraryPrompt {
    HINSTANCE instance;
    HFONT font;
    UINT dpi;
    HWND& active_dialog;
    const wchar_t* caption;
    const wchar_t* explanation;
    std::wstring value;
    const std::vector<LibraryChoice>* choices = nullptr;
    HWND input = nullptr;

    static INT_PTR CALLBACK handle(HWND dialog, UINT message, WPARAM wparam, LPARAM lparam) {
        auto self = reinterpret_cast<LibraryPrompt*>(GetWindowLongPtrW(dialog, DWLP_USER));
        if (message == WM_INITDIALOG) {
            self = reinterpret_cast<LibraryPrompt*>(lparam);
            SetWindowLongPtrW(dialog, DWLP_USER, reinterpret_cast<LONG_PTR>(self));
            self->active_dialog = dialog;
            self->prepare(dialog);
            return FALSE; // prepare sets the initial focus itself.
        }
        if (!self) return FALSE;
        if (message == WM_DESTROY) {
            if (self->active_dialog == dialog) self->active_dialog = nullptr;
            return FALSE;
        }
        if (message == WM_CLOSE || (message == WM_COMMAND && LOWORD(wparam) == IDCANCEL)) {
            EndDialog(dialog, IDCANCEL);
            return TRUE;
        }
        if (message != WM_COMMAND) return FALSE;
        const auto command = LOWORD(wparam);
        if (command != IDOK && !(self->choices && command == 100 && HIWORD(wparam) == LBN_DBLCLK)) return FALSE;
        if (self->choices) {
            const auto index = SendMessageW(self->input, LB_GETCURSEL, 0, 0);
            if (index < 0 || static_cast<size_t>(index) >= self->choices->size()) return TRUE;
            self->value = (*self->choices)[static_cast<size_t>(index)].id;
        } else {
            auto value = get_text(self->input);
            const auto start = value.find_first_not_of(L" \t\r\n");
            if (start == std::wstring::npos) {
                MessageBeep(MB_ICONWARNING);
                SetFocus(self->input);
                return TRUE;
            }
            value = value.substr(start, value.find_last_not_of(L" \t\r\n") - start + 1);
            self->value = std::move(value);
        }
        EndDialog(dialog, IDOK);
        return TRUE;
    }

    void prepare(HWND dialog) {
        auto px = [&](int value) { return MulDiv(value, static_cast<int>(dpi), 96); };
        SetWindowTextW(dialog, caption);
        constexpr int width = 450;
        const int input_height = choices ? 175 : 30;
        const int height = 104 + input_height;
        const int button_y = 63 + input_height;
        RECT size{0, 0, px(width), px(height)};
        AdjustWindowRectExForDpi(&size, static_cast<DWORD>(GetWindowLongPtrW(dialog, GWL_STYLE)), FALSE,
            static_cast<DWORD>(GetWindowLongPtrW(dialog, GWL_EXSTYLE)), dpi);
        RECT parent{};
        GetWindowRect(GetParent(dialog), &parent);
        const int w = size.right - size.left, h = size.bottom - size.top;
        MONITORINFO monitor{};
        monitor.cbSize = sizeof(monitor);
        const bool has_monitor = GetMonitorInfoW(MonitorFromWindow(dialog, MONITOR_DEFAULTTONEAREST), &monitor) != FALSE;
        int x = (parent.left + parent.right - w) / 2, y = (parent.top + parent.bottom - h) / 2;
        if (has_monitor) {
            x = std::clamp<LONG>(x, monitor.rcWork.left, std::max(monitor.rcWork.left, monitor.rcWork.right - w));
            y = std::clamp<LONG>(y, monitor.rcWork.top, std::max(monitor.rcWork.top, monitor.rcWork.bottom - h));
        }
        SetWindowPos(dialog, nullptr, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE);

        auto child = [&](const wchar_t* type, const wchar_t* label, DWORD style,
                         int id, int left, int top, int width_px, int height_px, DWORD extended = 0u) {
            const HWND control = CreateWindowExW(extended, type, label, WS_CHILD | WS_VISIBLE | style,
                px(left), px(top), px(width_px), px(height_px), dialog,
                reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), instance, nullptr);
            if (control) SendMessageW(control, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
            return control;
        };
        child(L"STATIC", explanation, SS_LEFT | SS_NOPREFIX, 0, 16, 12, width - 32, 30);
        if (choices) {
            input = child(L"LISTBOX", L"", WS_TABSTOP | WS_VSCROLL | WS_HSCROLL | LBS_NOTIFY | LBS_NOINTEGRALHEIGHT,
                100, 16, 47, width - 32, input_height, WS_EX_CLIENTEDGE);
            if (input) {
                int active = 0;
                int extent = 0;
                HDC dc = GetDC(input);
                const auto previous = dc ? SelectObject(dc, font) : nullptr;
                for (size_t i = 0; i < choices->size(); ++i) {
                    const auto& item = (*choices)[i];
                    if (SendMessageW(input, LB_ADDSTRING, 0, reinterpret_cast<LPARAM>(item.label.c_str())) < 0) {
                        ReleaseDC(input, dc);
                        EndDialog(dialog, IDCANCEL);
                        return;
                    }
                    if (item.id == value) active = static_cast<int>(i);
                    SIZE measured{};
                    if (dc && GetTextExtentPoint32W(dc, item.label.c_str(), static_cast<int>(item.label.size()), &measured))
                        extent = std::max(extent, static_cast<int>(measured.cx) + px(10));
                }
                if (dc) {
                    if (previous) SelectObject(dc, previous);
                    ReleaseDC(input, dc);
                }
                SendMessageW(input, LB_SETHORIZONTALEXTENT, extent, 0);
                SendMessageW(input, LB_SETCURSEL, active, 0);
            }
        } else {
            input = child(L"EDIT", value.c_str(), WS_TABSTOP | ES_AUTOHSCROLL, 100,
                16, 47, width - 32, input_height, WS_EX_CLIENTEDGE);
            if (input) {
                if (!restrict_clipboard(input)) {
                    EndDialog(dialog, IDCANCEL);
                    return;
                }
                SendMessageW(input, EM_SETLIMITTEXT, TitleLimit, 0);
                SendMessageW(input, EM_SETSEL, 0, -1);
            }
        }
        const HWND accept = child(L"BUTTON", L"&Valider", WS_TABSTOP | BS_DEFPUSHBUTTON,
            IDOK, width - 210, button_y, 94, 29);
        const HWND cancel = child(L"BUTTON", L"&Annuler", WS_TABSTOP | BS_PUSHBUTTON,
            IDCANCEL, width - 110, button_y, 94, 29);
        if (!input || !accept || !cancel) {
            EndDialog(dialog, IDCANCEL);
            return;
        }
        SendMessageW(dialog, DM_SETDEFID, IDOK, 0);
        SetFocus(input);
    }

    bool run(HWND parent) {
        struct alignas(DWORD) Template {
            DLGTEMPLATE dialog;
            WORD menu{};
            WORD klass{};
            WORD title{};
        } spec{};
        spec.dialog.style = WS_POPUP | WS_CAPTION | WS_SYSMENU | DS_MODALFRAME;
        spec.dialog.cx = 240;
        spec.dialog.cy = 100;
        return DialogBoxIndirectParamW(instance, &spec.dialog, parent, handle, reinterpret_cast<LPARAM>(this)) == IDOK;
    }
};

struct App {
    HINSTANCE instance{};
    HWND window{};
    HWND banner{}, new_note{}, dictate{}, save_button{}, privacy{}, vocab{};
    HWND library_label{}, library{}, title_label{}, title{}, body_label{}, body{}, draft_label{}, draft{};
    HWND folder_label{}, folder_tree{}, search_label{}, search_text{}, search_all{}, sort_by{}, new_folder{}, folder_actions{};
    HWND note_info{}, note_dates{}, move_note{}, mic_status{}, storage_status{}, masked_info{}, active_dialog{};
    HFONT font{};
    UINT dpi{96};
    notes::Store store;
    notes::Note current;
    std::vector<notes::Note> entries;
    std::vector<notes::Folder> folders;
    std::unordered_map<std::wstring, HTREEITEM> folder_items;
    std::wstring selected_folder;
    notes::Query query;
    bool all_notes = true;
    bool refreshing_tree = false;
    bool refreshing_notes = false;
    bool list_complete = true;
    bool search_pending = false;
    std::mutex event_mutex;
    std::deque<doct::EngineEvent> pending_events;
    std::unique_ptr<doct::Engine> engine;
    const bool dictation_cpu_supported = doct::Engine::cpu_supported();
    std::wstring runtime;
    std::wstring idle_status{L"Micro coupé · Prêt à dicter."};
    std::wstring interrupt_status;
    Phase phase{Phase::idle};
    std::uint64_t generation{};
    bool blocked_generation{};
    bool captured{};
    bool microphone_unconfirmed{};
    bool cancel_requested{};
    bool wts_registered{};
    bool session_locked{};
    bool masked{};
    bool loading{};
    bool dirty{};
    bool store_ready{};
    bool shutting_down{};
    bool close_requested{};

    HWND control(const wchar_t* klass, const wchar_t* label, DWORD style, int id = 0, DWORD ex_style = 0) const {
        return CreateWindowExW(ex_style, klass, label, WS_CHILD | WS_VISIBLE | style, 0, 0, 0, 0,
            window, id ? reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)) : nullptr, instance, nullptr);
    }

    bool create() {
        dpi = GetDpiForWindow(window);
        if (!dpi) dpi = 96;
        banner = control(L"STATIC", L"NoteVive 0.3.0 · Essai hors ligne — données fictives uniquement", SS_LEFT);
        new_note = control(L"BUTTON", L"+ &Transcription", WS_TABSTOP | BS_PUSHBUTTON, New);
        new_folder = control(L"BUTTON", L"+ &Dossier", WS_TABSTOP | BS_PUSHBUTTON, NewFolder);
        folder_actions = control(L"BUTTON", L"Dossier…", WS_TABSTOP | BS_PUSHBUTTON, FolderActions);
        dictate = control(L"BUTTON", L"&Dicter (F9)", WS_TABSTOP | BS_PUSHBUTTON, Dictate);
        save_button = control(L"BUTTON", L"&Enregistrer", WS_TABSTOP | BS_PUSHBUTTON, Save);
        privacy = control(L"BUTTON", L"&Masquer la note", WS_TABSTOP | BS_PUSHBUTTON, Privacy);
        vocab = control(L"BUTTON", L"&Vocabulaire", WS_TABSTOP | BS_PUSHBUTTON, Vocabulary);
        folder_label = control(L"STATIC", L"&Dossiers", SS_LEFT);
        folder_tree = control(WC_TREEVIEWW, L"", WS_TABSTOP | TVS_HASLINES | TVS_LINESATROOT | TVS_HASBUTTONS | TVS_SHOWSELALWAYS,
            FolderTree, WS_EX_CLIENTEDGE);
        search_label = control(L"STATIC", L"&Rechercher dans le titre ou le texte", SS_LEFT);
        search_text = control(L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL, SearchText, WS_EX_CLIENTEDGE);
        search_all = control(L"BUTTON", L"Dans tous les dossiers", WS_TABSTOP | BS_AUTOCHECKBOX, SearchAll);
        sort_by = control(L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL, SortBy);
        library_label = control(L"STATIC", L"Transcriptions locales", SS_LEFT | SS_NOPREFIX);
        library = control(L"LISTBOX", L"", WS_TABSTOP | WS_HSCROLL | WS_VSCROLL | LBS_NOTIFY | LBS_NOINTEGRALHEIGHT,
            Library, WS_EX_CLIENTEDGE);
        title_label = control(L"STATIC", L"&Titre", SS_LEFT);
        title = control(L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL, Title, WS_EX_CLIENTEDGE);
        note_info = control(L"STATIC", L"", SS_LEFT | SS_NOPREFIX | SS_ENDELLIPSIS, NoteInfo);
        note_dates = control(L"STATIC", L"", SS_LEFT | SS_NOPREFIX | SS_ENDELLIPSIS);
        move_note = control(L"BUTTON", L"&Classer…", WS_TABSTOP | BS_PUSHBUTTON, MoveNote);
        body_label = control(L"STATIC", L"T&exte de la note (modifiable)", SS_LEFT);
        body = control(L"EDIT", L"", WS_TABSTOP | ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN | WS_VSCROLL,
            Body, WS_EX_CLIENTEDGE);
        draft_label = control(L"STATIC", L"Dernier passage dicté — vérifier doses, unités et négations", SS_LEFT);
        draft = control(L"EDIT", L"", ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL,
            Draft, WS_EX_CLIENTEDGE);
        mic_status = control(L"STATIC", L"Micro coupé", SS_LEFT | SS_NOPREFIX);
        storage_status = control(L"STATIC", L"", SS_LEFT | SS_NOPREFIX);
        masked_info = control(L"STATIC", L"Bibliothèque masquée. Réaffichez-la explicitement pour reprendre.", SS_LEFT);
        for (HWND item : controls()) if (!item) return false;
        for (HWND item : {title, body, draft, search_text}) if (!restrict_clipboard(item)) return false;
        SendMessageW(search_text, EM_SETLIMITTEXT, 240, 0);
        SendMessageW(search_text, EM_SETCUEBANNER, FALSE, reinterpret_cast<LPARAM>(L"Rechercher une transcription"));
        for (const wchar_t* label : {L"Dernière modification", L"Date de création", L"Titre (A à Z)"})
            if (SendMessageW(sort_by, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(label)) < 0) return false;
        SendMessageW(sort_by, CB_SETCURSEL, 0, 0);
        SendMessageW(title, EM_SETLIMITTEXT, TitleLimit, 0);
        SendMessageW(body, EM_SETLIMITTEXT, TextLimit, 0);
        SendMessageW(draft, EM_SETLIMITTEXT, TextLimit, 0);
        update_font();
        runtime = runtime_path();
        wts_registered = WTSRegisterSessionNotification(window, NOTIFY_FOR_THIS_SESSION) != FALSE;
        if (!wts_registered) idle_status = L"Micro coupé · Dictée indisponible : verrouillage de session non surveillé.";
        if (runtime.empty()) idle_status = L"Micro coupé · Dossier du moteur introuvable.";
        if (dictation_cpu_supported) engine = std::make_unique<doct::Engine>([this, target = window](doct::EngineEvent value) {
            {
                std::lock_guard<std::mutex> lock(event_mutex);
                if (value.kind == doct::EngineEventKind::partial && !pending_events.empty()
                        && pending_events.back().kind == doct::EngineEventKind::partial
                        && pending_events.back().generation == value.generation) {
                    pending_events.back() = std::move(value);
                } else {
                    pending_events.push_back(std::move(value));
                }
            }
            PostMessageW(target, EngineMessage, 0, 0);
        });
        std::wstring error;
        store_ready = store.Open(error);
        if (store_ready) {
            refresh_folders();
            reload_library();
        }
        else set_storage(error.empty() ? L"Stockage local indisponible." : error);
        if (store_ready && GetWindowTextLengthW(storage_status) == 0) {
            set_storage(entries.empty() ? L"Aucune note sauvegardée."
                                        : L"Brouillon vide · Choisissez une note locale pour la rouvrir.");
        }
        update_controls();
        set_note_info();
        layout();
        return true;
    }

    std::vector<HWND> controls() const {
        return {banner, new_note, new_folder, folder_actions, dictate, save_button, privacy, vocab,
            folder_label, folder_tree, search_label, search_text, search_all, sort_by, library_label, library,
            title_label, title, note_info, note_dates, move_note, body_label, body, draft_label, draft,
            mic_status, storage_status, masked_info};
    }

    void update_font() {
        NONCLIENTMETRICSW metrics{};
        metrics.cbSize = sizeof(metrics);
        HFONT next = nullptr;
        if (SystemParametersInfoForDpi(SPI_GETNONCLIENTMETRICS, sizeof(metrics), &metrics, 0, dpi)) {
            next = CreateFontIndirectW(&metrics.lfMessageFont);
        }
        const auto chosen = next ? next : static_cast<HFONT>(GetStockObject(DEFAULT_GUI_FONT));
        for (HWND item : controls()) if (item) SendMessageW(item, WM_SETFONT, reinterpret_cast<WPARAM>(chosen), TRUE);
        if (font) DeleteObject(font);
        font = next;
    }

    int px(int value) const { return MulDiv(value, static_cast<int>(dpi), 96); }

    void layout() const {
        RECT rect{};
        GetClientRect(window, &rect);
        const int width = static_cast<int>(rect.right);
        const int height = static_cast<int>(rect.bottom);
        const int gap = px(12), left = px(16), right = width - left;
        const int side = std::clamp(width * 35 / 100, px(202), px(330));
        const int edit_x = left + side + gap;
        const int edit_w = std::max(0, right - edit_x);
        auto move = [](HWND item, int x, int y, int w, int h) {
            if (item) MoveWindow(item, x, y, std::max(0, w), std::max(0, h), TRUE);
        };
        const bool compact = width < px(685);
        move(banner, left, px(10), right - left, compact ? px(34) : px(23));
        int x = left;
        int toolbar_y = compact ? px(45) : px(38);
        auto button = [&](HWND item, int w) {
            if (x != left && x + px(w) > right) {
                x = left;
                toolbar_y += px(36);
            }
            move(item, x, toolbar_y, px(w), px(32));
            x += px(w + 7);
        };
        button(dictate, 154);
        button(save_button, 100);
        button(privacy, 140);
        button(vocab, 108);
        const int content_top = toolbar_y + px(69);
        const int content_bottom = height - px(43);
        const int provisional_h = std::clamp((content_bottom - content_top) / 5, px(40), px(86));
        const int provisional_top = content_bottom - provisional_h;
        move(mic_status, left, toolbar_y + px(36), right - left, px(30));
        int li = content_top;
        const int button_gap = px(6), folder_width = px(84);
        move(new_note, left, li, side - folder_width - button_gap, px(29));
        move(new_folder, left + side - folder_width, li, folder_width, px(29));
        li += px(35);
        move(folder_label, left, li + px(3), side - px(93), px(20));
        move(folder_actions, left + side - px(89), li, px(89), px(25));
        li += px(28);
        const int folder_height = std::clamp((content_bottom - content_top - px(112)) / 3, px(54), px(176));
        move(folder_tree, left, li, side, folder_height);
        li += folder_height + px(8);
        move(search_label, left, li, side, px(18));
        move(search_text, left, li + px(19), side, px(25));
        move(search_all, left, li + px(46), side, px(21));
        move(sort_by, left, li + px(71), side, px(140));
        li += px(101);
        move(library_label, left, li, side, px(18));
        move(library, left, li + px(19), side, content_bottom - li - px(19));
        move(title_label, edit_x, content_top, edit_w, px(18));
        move(title, edit_x, content_top + px(20), edit_w - px(101), px(28));
        move(move_note, right - px(95), content_top + px(20), px(95), px(28));
        move(note_info, edit_x, content_top + px(52), edit_w, px(18));
        move(note_dates, edit_x, content_top + px(71), edit_w, px(19));
        move(body_label, edit_x, content_top + px(95), edit_w, px(18));
        move(body, edit_x, content_top + px(115), edit_w, provisional_top - content_top - px(138));
        move(draft_label, edit_x, provisional_top - px(21), edit_w, px(20));
        move(draft, edit_x, provisional_top, edit_w, provisional_h);
        move(storage_status, left, height - px(38), right - left, px(34));
        move(masked_info, left, content_top + px(36), right - left, px(40));
    }

    void set_storage(const std::wstring& label) const {
        SetWindowTextW(storage_status, label.c_str());
    }

    void update_controls() {
        const bool idle = phase == Phase::idle;
        const bool visible = !masked && !session_locked;
        for (HWND item : {new_note, new_folder, folder_actions, dictate, save_button, vocab, folder_label,
                           folder_tree, search_label, search_text, search_all, sort_by, library_label, library,
                           title_label, title, note_info, note_dates, move_note, body_label, body, draft_label, draft, storage_status}) {
            ShowWindow(item, visible ? SW_SHOW : SW_HIDE);
        }
        ShowWindow(masked_info, visible ? SW_HIDE : SW_SHOW);
        EnableWindow(privacy, !session_locked);
        SetWindowTextW(privacy, visible ? L"&Masquer la note" : L"&Réafficher la note");
        for (HWND item : {new_note, new_folder, folder_tree, search_text, sort_by, library}) {
            EnableWindow(item, idle && store_ready);
        }
        EnableWindow(search_all, idle && store_ready && !all_notes);
        EnableWindow(folder_actions, idle && store_ready && !all_notes && !selected_folder.empty());
        EnableWindow(move_note, idle && store_ready);
        EnableWindow(save_button, store_ready);
        EnableWindow(vocab, idle && !runtime.empty());
        EnableWindow(title, store_ready);
        EnableWindow(body, store_ready);
        EnableWindow(dictate, dictation_cpu_supported && !close_requested && store_ready && wts_registered && !runtime.empty() && !microphone_unconfirmed
            && (phase == Phase::idle || phase == Phase::listening || phase == Phase::preparing));
        const wchar_t* button_text = L"&Dicter (F9)";
        const wchar_t* status = idle_status.c_str();
        switch (phase) {
        case Phase::idle: break;
        case Phase::preparing:
            button_text = L"&Annuler (F9)";
            status = L"Micro coupé · Préparation du moteur.";
            break;
        case Phase::listening:
            button_text = L"&Arrêter (F9)";
            status = L"Micro ouvert · Les phrases s’ajoutent après les pauses et le calcul.";
            break;
        case Phase::stopping:
            button_text = L"Arrêt demandé…";
            status = captured ? L"Micro ouvert · Arrêt demandé…" : L"Arrêt demandé · Vérification du micro…";
            break;
        case Phase::finalizing:
            button_text = L"Finalisation…";
            status = cancel_requested ? L"Micro coupé · Dictée interrompue." : L"Micro coupé · Finalisation du texte…";
            break;
        }
        if (!dictation_cpu_supported) status = doct::Engine::cpu_requirement();
        if (microphone_unconfirmed) status = L"Arrêt du microphone non confirmé. Fermez l’application.";
        SetWindowTextW(dictate, button_text);
        SetWindowTextW(mic_status, status);
    }

    static const std::wstring& all_key() {
        static const std::wstring key = L"*";
        return key;
    }

    bool can_organize() const {
        return phase == Phase::idle && !masked && !session_locked && !shutting_down && !close_requested
            && store_ready && !active_dialog;
    }

    void set_note_info() const {
        const auto path = notes::FolderPath(folders, current.folder_id);
        const auto text = current.folder_id.empty() ? L"Sans dossier"
            : path.empty() ? L"Dossier indisponible" : path;
        SetWindowTextW(note_info, text.c_str());
        const auto dates = current.created.empty() ? std::wstring{} : L"Créée : " + note_date(current.created) +
            L"   ·   Modifiée : " + note_date(current.modified) + L" (UTC)";
        SetWindowTextW(note_dates, dates.c_str());
    }

    void select_folder(bool all, const std::wstring& id) {
        const bool previous = refreshing_tree;
        refreshing_tree = true;
        if (auto found = folder_items.find(all ? all_key() : id); found != folder_items.end()) {
            TreeView_SelectItem(folder_tree, found->second);
            TreeView_EnsureVisible(folder_tree, found->second);
        }
        refreshing_tree = previous;
    }

    void refresh_folders() {
        std::unordered_set<std::wstring> expanded;
        for (const auto& [id, item] : folder_items) {
            if (TreeView_GetItemState(folder_tree, item, TVIS_EXPANDED) & TVIS_EXPANDED) expanded.insert(id);
        }

        std::wstring error;
        const bool complete = store.ListFolders(folders, error);
        if (!all_notes && !selected_folder.empty() && std::none_of(folders.begin(), folders.end(), [&](const auto& f) {
                    return f.id == selected_folder;
                })) {
            all_notes = true;
            selected_folder.clear();
        }
        std::unordered_map<std::wstring, std::vector<size_t>> children;
        for (size_t i = 0; i < folders.size(); ++i) children[folders[i].parent_id].push_back(i);
        refreshing_tree = true;
        SendMessageW(folder_tree, WM_SETREDRAW, FALSE, 0);
        TreeView_DeleteAllItems(folder_tree);
        folder_items.clear();
        auto insert = [&](HTREEITEM parent, const wchar_t* title, const std::wstring& id, LPARAM tag, bool sorted) {
            TVINSERTSTRUCTW item{};
            item.hParent = parent;
            item.hInsertAfter = sorted ? TVI_SORT : TVI_LAST;
            item.item.mask = TVIF_TEXT | TVIF_PARAM;
            item.item.pszText = const_cast<wchar_t*>(title);
            item.item.lParam = tag;
            auto result = reinterpret_cast<HTREEITEM>(SendMessageW(folder_tree, TVM_INSERTITEMW, 0,
                reinterpret_cast<LPARAM>(&item)));
            if (result) folder_items.emplace(id, result);
            return result;
        };
        const auto root = insert(TVI_ROOT, L"Toutes les transcriptions", all_key(), 0, false);
        const auto unfiled = insert(TVI_ROOT, L"Sans dossier", L"", 1, false);
        auto build = [&](const auto& add_children, const std::wstring& parent, HTREEITEM tree_parent, size_t depth) -> void {
            if (!tree_parent || depth > notes::kMaxFolderDepth) return;
            const auto direct = children.find(parent);
            if (direct == children.end()) return;
            for (const auto i : direct->second) {
                const auto& item = folders[i];
                if (folder_items.count(item.id)) continue;
                auto created = insert(tree_parent, item.title.c_str(), item.id, static_cast<LPARAM>(i + 2), true);
                if (created) add_children(add_children, item.id, created, depth + 1);
            }
        };
        build(build, L"", root, 1);
        if (root) TreeView_Expand(folder_tree, root, TVE_EXPAND);
        for (const auto& id : expanded) {
            if (auto it = folder_items.find(id); it != folder_items.end()) TreeView_Expand(folder_tree, it->second, TVE_EXPAND);
        }
        select_folder(all_notes, selected_folder);
        SendMessageW(folder_tree, WM_SETREDRAW, TRUE, 0);
        InvalidateRect(folder_tree, nullptr, TRUE);
        refreshing_tree = false;
        if (!complete || !root || !unfiled || folder_items.size() != folders.size() + 2) {
            SetWindowTextW(folder_label, L"&Dossiers (liste partielle)");
            set_storage(error.empty() ? L"Certains dossiers ne sont pas accessibles." : error);
        } else {
            SetWindowTextW(folder_label, L"&Dossiers");
        }
        set_note_info();
    }

    void choose_current() const {
        auto found = std::find_if(entries.begin(), entries.end(), [&](const notes::Note& item) { return item.id == current.id; });
        const auto index = found == entries.end() ? LB_ERR : static_cast<LRESULT>(found - entries.begin());
        SendMessageW(library, LB_SETCURSEL, static_cast<WPARAM>(index), 0);
    }

    void render_library(bool complete = true) {
        refreshing_notes = true;
        SendMessageW(library, WM_SETREDRAW, FALSE, 0);
        SendMessageW(library, LB_RESETCONTENT, 0, 0);
        auto dc = GetDC(library);
        const auto old_font = dc ? SelectObject(dc, font ? font : GetStockObject(DEFAULT_GUI_FONT)) : nullptr;
        int extent = 0;
        size_t inserted = 0;
        for (const auto& item : entries) {
            const auto caption = list_caption(item, query.sort);
            if (SendMessageW(library, LB_ADDSTRING, 0, reinterpret_cast<LPARAM>(caption.c_str())) < 0) break;
            ++inserted;
            SIZE measured{};
            if (dc && GetTextExtentPoint32W(dc, caption.c_str(), static_cast<int>(caption.size()), &measured))
                extent = std::max(extent, static_cast<int>(measured.cx) + px(10));
        }
        if (dc) {
            if (old_font) SelectObject(dc, old_font);
            ReleaseDC(library, dc);
        }
        SendMessageW(library, LB_SETHORIZONTALEXTENT, extent, 0);
        complete = complete && inserted == entries.size();
        entries.resize(inserted);
        choose_current();
        SendMessageW(library, WM_SETREDRAW, TRUE, 0);
        InvalidateRect(library, nullptr, TRUE);
        auto count = std::to_wstring(entries.size()) + (entries.size() == 1 ? L" transcription" : L" transcriptions");
        if (!complete) count += L" · liste partielle";
        else if (!query.text.empty()) count += L" trouvée(s)";
        SetWindowTextW(library_label, count.c_str());
        refreshing_notes = false;
    }

    void reload_library() {
        KillTimer(window, SearchTimer);
        search_pending = false;
        query.text = get_text(search_text);
        query.filter_folder = !all_notes && (query.text.empty() || SendMessageW(search_all, BM_GETCHECK, 0, 0) != BST_CHECKED);
        query.folder_id = selected_folder;
        query.include_descendants = !selected_folder.empty();
        switch (SendMessageW(sort_by, CB_GETCURSEL, 0, 0)) {
        case 1: query.sort = notes::Sort::CreatedNewest; break;
        case 2: query.sort = notes::Sort::TitleAscending; break;
        default: query.sort = notes::Sort::ModifiedNewest; break;
        }
        std::wstring error;
        list_complete = store.List(query, entries, error);
        render_library(list_complete);
        if (!list_complete) set_storage(error.empty() ? L"Certaines notes locales ne sont pas lisibles." : error);
    }

    void update_saved_entry() {
        entries.erase(std::remove_if(entries.begin(), entries.end(), [&](const auto& note) {
            return note.id == current.id;
        }), entries.end());
        if (notes::Matches(query, current, folders)) {
            notes::Note entry;
            entry.id = current.id;
            entry.title = current.title;
            entry.created = current.created;
            entry.modified = current.modified;
            entry.folder_id = current.folder_id;
            entries.push_back(std::move(entry));
            notes::SortNotes(entries, query.sort);
        }
        render_library(list_complete);
        set_note_info();
    }

    void change_folder(LPARAM tag) {
        if (refreshing_tree) return;
        if (!can_organize() || tag < 0 || (tag >= 2 && static_cast<size_t>(tag - 2) >= folders.size()) || !save_note()) {
            select_folder(all_notes, selected_folder);
            return;
        }
        all_notes = tag == 0;
        selected_folder = tag >= 2 ? folders[static_cast<size_t>(tag - 2)].id : L"";
        reload_library();
        update_controls();
    }

    void search_changed() {
        if (!can_organize()) return;
        search_pending = true;
        if (!SetTimer(window, SearchTimer, SearchDelayMs, nullptr)) reload_library();
    }

    HFONT dialog_font() const {
        return font ? font : static_cast<HFONT>(GetStockObject(DEFAULT_GUI_FONT));
    }

    bool prompt_text(const wchar_t* caption, const wchar_t* description, std::wstring& name) {
        LibraryPrompt prompt{instance, dialog_font(), dpi, active_dialog, caption, description, name};
        if (!prompt.run(window) || !can_organize()) return false;
        name = std::move(prompt.value);
        return true;
    }

    bool choose_destination(const wchar_t* caption, const wchar_t* explanation, std::wstring& id,
                            const std::wstring& exclude = {}) {
        std::vector<LibraryChoice> options;
        std::unordered_set<std::wstring> skipped;
        if (!exclude.empty()) {
            skipped.insert(exclude);
            // A folder cannot be moved into itself or any child.
            for (size_t level = 0; level < notes::kMaxFolderDepth; ++level) {
                bool changed = false;
                for (const auto& folder : folders) {
                    if (skipped.count(folder.parent_id)) changed |= skipped.insert(folder.id).second;
                }
                if (!changed) break;
            }
        }
        for (const auto& folder : folders) {
            if (!skipped.count(folder.id)) {
                auto label = notes::FolderPath(folders, folder.id);
                if (!label.empty()) options.push_back({std::move(label), folder.id});
            }
        }
        std::sort(options.begin(), options.end(), [](const auto& a, const auto& b) {
            const auto cmp = CompareStringEx(L"fr-FR", NORM_IGNORECASE | NORM_IGNORENONSPACE,
                a.label.c_str(), -1, b.label.c_str(), -1, nullptr, nullptr, 0);
            if (!cmp) return a.label == b.label ? a.id < b.id : a.label < b.label;
            return cmp == CSTR_LESS_THAN || (cmp == CSTR_EQUAL && a.id < b.id);
        });
        options.insert(options.begin(), {exclude.empty() ? L"Sans dossier" : L"À la racine", L""});
        LibraryPrompt prompt{instance, dialog_font(), dpi, active_dialog, caption, explanation, id, &options};
        if (!prompt.run(window) || !can_organize()) return false;
        id = std::move(prompt.value);
        return true;
    }

    notes::Folder* selected_item() {
        if (all_notes || selected_folder.empty()) return nullptr;
        const auto found = std::find_if(folders.begin(), folders.end(), [&](const auto& item) { return item.id == selected_folder; });
        return found == folders.end() ? nullptr : &*found;
    }

    void show_folder_actions() {
        if (!can_organize() || !selected_item()) return;
        const auto menu = CreatePopupMenu();
        if (!menu) return;
        AppendMenuW(menu, MF_STRING, RenameFolder, L"&Renommer le dossier");
        AppendMenuW(menu, MF_STRING, MoveFolder, L"&Déplacer le dossier…");
        RECT rect{};
        GetWindowRect(folder_actions, &rect);
        const auto action = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_LEFTALIGN | TPM_TOPALIGN,
            rect.left, rect.bottom, 0, window, nullptr);
        DestroyMenu(menu);
        if (action == RenameFolder || action == MoveFolder) change_folder_metadata(action);
    }

    void change_folder_metadata(int action) {
        if (!can_organize() || !save_note()) return;
        notes::Folder pending;
        auto existing = selected_item();
        const bool creating = action == NewFolder;
        if (creating) {
            if (existing) pending.parent_id = existing->id;
        } else if (existing) {
            pending = *existing;
        } else {
            return;
        }
        if (action == MoveFolder) {
            if (!choose_destination(L"Déplacer le dossier", L"Choisissez le nouveau dossier parent.",
                    pending.parent_id, pending.id) || pending.parent_id == existing->parent_id) return;
        } else {
            const auto location = notes::FolderPath(folders, pending.parent_id);
            const std::wstring description = creating ? (location.empty() ? L"Nom du dossier à la racine :"
                : L"Nom du sous-dossier à créer dans « " + location + L" » :") : L"Nouveau nom du dossier :";
            if (!prompt_text(creating ? L"Nouveau dossier" : L"Renommer le dossier", description.c_str(), pending.title)) return;
        }
        std::wstring error;
        if (!store.SaveFolder(pending, error)) {
            refresh_folders();
            reload_library();
            set_storage(error.empty() ? L"Le dossier n’a pas pu être enregistré." : error);
            return;
        }
        all_notes = false;
        selected_folder = pending.id;
        refresh_folders();
        reload_library();
        set_storage(L"Dossier enregistré localement.");
        update_controls();
        SetFocus(folder_tree);
    }

    void move_current_note() {
        if (!can_organize()) return;
        auto destination = current.folder_id;
        if (!choose_destination(L"Classer la transcription", L"Choisissez un dossier de destination.", destination) ||
            destination == current.folder_id) return;
        auto pending = current;
        pending.title = get_text(title);
        pending.text = get_text(body);
        if (pending.id.empty() && pending.title.empty() && pending.text.empty()) {
            current.folder_id = std::move(destination);
            set_note_info();
            set_storage(L"Ce brouillon sera classé à la première sauvegarde.");
            return;
        }
        pending.folder_id = std::move(destination);
        // Write the editor and the destination together. In particular, an unsaved
        // draft linked to a missing folder can still be rescued to the root.
        KillTimer(window, SaveTimer);
        std::wstring error;
        if (!store.Save(pending, error)) {
            set_storage(error.empty() ? L"La transcription n’a pas pu être déplacée." : error);
            return;
        }
        current = std::move(pending);
        dirty = false;
        update_saved_entry();
        set_storage(L"Transcription classée.");
    }

    void place_note(notes::Note note) {
        KillTimer(window, SaveTimer);
        current = std::move(note);
        loading = true;
        const std::wstring normalized = editor_text(current.text);
        SetWindowTextW(title, current.title.c_str());
        SetWindowTextW(body, normalized.c_str());
        SetWindowTextW(draft, L"");
        SendMessageW(body, EM_EMPTYUNDOBUFFER, 0, 0);
        loading = false;
        dirty = false;
        set_storage(current.id.empty() ? L"Nouvelle transcription · La sauvegarde commence après la première modification."
                                      : L"Note chargée · Modifications sauvegardées localement.");
        choose_current();
        set_note_info();
    }

    bool load_note(const std::wstring& id) {
        notes::Note note;
        std::wstring error;
        if (!store.Load(id, note, error)) {
            set_storage(error.empty() ? L"Impossible d’ouvrir cette note." : error);
            choose_current();
            return false;
        }
        place_note(std::move(note));
        return true;
    }

    void change_note() {
        if (refreshing_notes) return;
        const auto index = SendMessageW(library, LB_GETCURSEL, 0, 0);
        if (index < 0 || static_cast<std::size_t>(index) >= entries.size()) return;
        // Saving refreshes the list; capture the opaque ID before doing it.
        const auto id = entries[static_cast<std::size_t>(index)].id;
        if (!can_organize() || id == current.id || !save_note()) {
            choose_current();
            return;
        }
        load_note(id);
    }

    void mark_dirty() {
        if (loading || !store_ready) return;
        dirty = true;
        set_storage(L"Modifications en attente de sauvegarde…");
        SetTimer(window, SaveTimer, SaveDelayMs, nullptr);
    }

    bool save_note(bool recovery = false) {
        KillTimer(window, SaveTimer);
        if (!dirty) return true;
        if (!store_ready) return false;
        notes::Note pending = current;
        pending.title = get_text(title);
        pending.text = get_text(body);
        if (pending.title.size() > TitleLimit || pending.text.size() > TextLimit) {
            set_storage(L"Note trop longue · Raccourcissez-la avant d’enregistrer.");
            return false;
        }
        if (pending.id.empty() && pending.title.empty() && pending.text.empty()) {
            dirty = false;
            set_storage(L"Brouillon vide · Rien à sauvegarder.");
            return true;
        }
        std::wstring error;
        bool recovered = false;
        if (!store.Save(pending, error)) {
            set_storage(error.empty() ? L"Sauvegarde impossible · Le texte reste dans cet éditeur." : error);
            if (!recovery || pending.id.empty() || masked || session_locked || phase != Phase::idle) return false;
            if (MessageBoxW(window, L"Cette note n’a pas pu être mise à jour. Enregistrer son contenu dans une nouvelle note ?\n\n"
                    L"La version précédente restera intacte. Si le dossier est inaccessible, la copie sera classée dans « Sans dossier ».",
                    L"NoteVive", MB_YESNO | MB_DEFBUTTON2 | MB_ICONQUESTION) != IDYES) {
                return false;
            }
            if (masked || session_locked) return false;
            if (!store.SaveRecoveryCopy(pending, error)) {
                set_storage(error.empty() ? L"Impossible de sauvegarder la copie." : error);
                return false;
            }
            recovered = true;
        }
        current = std::move(pending);
        dirty = false;
        if (recovered) {
            // Reload the original's metadata and make the selected copy visible
            // even if the previous search or folder filter excluded it.
            all_notes = !current.folder_id.empty();
            selected_folder.clear();
            select_folder(all_notes, selected_folder);
            SetWindowTextW(search_text, L"");
            reload_library();
            set_note_info();
            update_controls();
            set_storage(current.folder_id.empty() ? L"Copie sauvegardée dans « Sans dossier »." : L"Copie sauvegardée localement.");
        } else {
            set_storage(L"Brouillon sauvegardé localement · À relire.");
            update_saved_entry();
        }
        return true;
    }

    void new_blank() {
        if (!can_organize() || !save_note()) return;
        notes::Note blank;
        blank.folder_id = selected_folder;
        place_note(std::move(blank));
        SetFocus(title);
    }

    void rename_note() {
        if (!can_organize() || current.id.empty()) return;
        SetFocus(title);
        SendMessageW(title, EM_SETSEL, 0, -1);
    }

    void start_or_stop() {
        if (!dictation_cpu_supported || session_locked || masked || shutting_down || close_requested || active_dialog || !store_ready || !wts_registered || runtime.empty()
                || microphone_unconfirmed) return;
        if (phase == Phase::listening) {
            phase = Phase::stopping;
            engine->stop();
        } else if (phase == Phase::preparing) {
            cancel_capture(L"Micro coupé · Démarrage annulé.");
        } else if (phase == Phase::idle) {
            if (get_text(body).size() >= TextLimit) {
                idle_status = L"Micro coupé · Note pleine. Créez une nouvelle note.";
            } else {
                blocked_generation = cancel_requested = captured = false;
                interrupt_status.clear();
                SetWindowTextW(draft, L"");
                if (engine->start(++generation, runtime)) phase = Phase::preparing;
                else idle_status = L"Micro coupé · Moteur indisponible. Réessayez après quelques instants.";
            }
        }
        update_controls();
    }

    void cancel_capture(const wchar_t* next_status) {
        idle_status = next_status;
        if (phase != Phase::idle && engine) {
            blocked_generation = cancel_requested = true;
            interrupt_status = next_status;
            if (phase != Phase::finalizing) phase = Phase::stopping;
            engine->cancel();
        }
        SetWindowTextW(draft, L"");
        update_controls();
    }

    void conceal(const wchar_t* reason) {
        masked = true;
        if (active_dialog) EndDialog(active_dialog, IDCANCEL);
        cancel_capture(reason);
        save_note();
        if (!session_locked) SetFocus(privacy);
    }

    void toggle_privacy() {
        if (session_locked) return;
        if (masked) {
            masked = false;
            if (store_ready) reload_library();
            update_controls();
            if (store_ready) SetFocus(body);
        } else {
            conceal(L"Micro coupé · Note masquée. Aucune reprise automatique.");
        }
    }

    void append_final(const std::wstring& segment) {
        std::wstring text = editor_text(segment);
        if (text.find_first_not_of(L" \t\r\n") == std::wstring::npos) return;
        const std::wstring prior = get_text(body);
        if (!prior.empty() && prior.back() != L'\r' && prior.back() != L'\n') text.insert(0, L"\r\n");
        if (prior.size() > TextLimit || text.size() > TextLimit - prior.size()) {
            cancel_capture(L"Micro coupé · Note pleine. Le dernier passage doit être redicté.");
            return;
        }
        DWORD selection_start = 0, selection_end = 0;
        SendMessageW(body, EM_GETSEL, reinterpret_cast<WPARAM>(&selection_start), reinterpret_cast<LPARAM>(&selection_end));
        const LRESULT top = SendMessageW(body, EM_GETFIRSTVISIBLELINE, 0, 0);
        const bool follow_tail = GetFocus() != body && selection_start == prior.size() && selection_end == prior.size();
        SendMessageW(body, WM_SETREDRAW, FALSE, 0);
        SendMessageW(body, EM_SETSEL, prior.size(), static_cast<LPARAM>(prior.size()));
        SendMessageW(body, EM_REPLACESEL, TRUE, reinterpret_cast<LPARAM>(text.c_str()));
        if (follow_tail) {
            const auto end = prior.size() + text.size();
            SendMessageW(body, EM_SETSEL, end, static_cast<LPARAM>(end));
            SendMessageW(body, EM_SCROLLCARET, 0, 0);
        } else {
            SendMessageW(body, EM_SETSEL, selection_start, selection_end);
            const auto now = SendMessageW(body, EM_GETFIRSTVISIBLELINE, 0, 0);
            SendMessageW(body, EM_LINESCROLL, 0, top - now);
        }
        SendMessageW(body, WM_SETREDRAW, TRUE, 0);
        InvalidateRect(body, nullptr, TRUE);
        mark_dirty();
        save_note();
    }

    void on_engine(doct::EngineEvent& event) {
        if (shutting_down || event.generation != generation || phase == Phase::idle) return;
        switch (event.kind) {
        case doct::EngineEventKind::started:
            captured = true;
            if (phase == Phase::preparing) phase = Phase::listening;
            break;
        case doct::EngineEventKind::partial:
            if (!blocked_generation && !masked && !session_locked) {
                const std::wstring partial = editor_text(event.text);
                SetWindowTextW(draft, partial.c_str());
            }
            return;
        case doct::EngineEventKind::final:
            if (!blocked_generation && !masked && !session_locked) {
                append_final(event.text);
                if (!blocked_generation) SetWindowTextW(draft, editor_text(event.text).c_str());
            }
            return;
        case doct::EngineEventKind::capture_stopped:
            captured = false;
            phase = Phase::finalizing;
            break;
        case doct::EngineEventKind::stopped:
            phase = Phase::idle;
            captured = false;
            idle_status = interrupt_status.empty() ? L"Micro coupé · Dictée terminée. Relisez le texte." : interrupt_status;
            break;
        case doct::EngineEventKind::error:
            phase = Phase::idle;
            captured = false;
            microphone_unconfirmed = event.capture_unconfirmed;
            idle_status = interrupt_status.empty()
                ? (event.text.empty() ? L"Micro coupé · Dictée interrompue. Le texte stable est conservé."
                                      : L"Micro coupé · " + event.text)
                : interrupt_status;
            SetWindowTextW(draft, L"");
            break;
        }
        update_controls();
        if (phase == Phase::idle && close_requested) PostMessageW(window, WM_CLOSE, 0, 0);
        else if (search_pending && can_organize()) reload_library();
    }

    void drain_engine() {
        std::deque<doct::EngineEvent> batch;
        {
            std::lock_guard<std::mutex> lock(event_mutex);
            batch.swap(pending_events);
        }
        for (auto& event : batch) on_engine(event);
    }

    void close() {
        if (phase != Phase::idle) {
            close_requested = true;
            if (phase == Phase::preparing) {
                cancel_capture(L"Micro coupé · Démarrage annulé.");
            } else if (phase == Phase::listening) {
                phase = Phase::stopping;
                engine->stop();
            }
            update_controls();
            return;
        }
        close_requested = false;
        if (!save_note(true)) {
            update_controls();
            MessageBoxW(window, L"La note n’a pas pu être sauvegardée. Le texte est toujours dans l’éditeur.\n"
                L"Réessayez d’enregistrer avant de fermer.", L"NoteVive", MB_OK | MB_ICONWARNING);
            return;
        }
        shutdown();
        DestroyWindow(window);
    }

    void shutdown() {
        if (shutting_down) return;
        shutting_down = true;
        KillTimer(window, SaveTimer);
        KillTimer(window, SearchTimer);
        if (engine) engine->shutdown();
        // The worker cannot post after shutdown; release messages not consumed by the window.
        pending_events.clear();
        MSG message{};
        while (PeekMessageW(&message, window, EngineMessage, EngineMessage, PM_REMOVE)) {}
        if (wts_registered) WTSUnRegisterSessionNotification(window);
        if (font) {
            const auto stock = GetStockObject(DEFAULT_GUI_FONT);
            for (HWND item : controls()) if (item) SendMessageW(item, WM_SETFONT, reinterpret_cast<WPARAM>(stock), FALSE);
            DeleteObject(font);
            font = nullptr;
        }
    }
};

LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_NCCREATE) {
        auto app = static_cast<App*>(reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams);
        app->window = window;
        SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
    }
    auto app = reinterpret_cast<App*>(GetWindowLongPtrW(window, GWLP_USERDATA));
    if (!app) return DefWindowProcW(window, message, wparam, lparam);
    switch (message) {
    case WM_CREATE:
        return app->create() ? 0 : -1;
    case WM_SIZE:
        if (wparam == SIZE_MINIMIZED && app->phase != Phase::idle) {
            app->conceal(L"Micro coupé · Dictée interrompue lors de la réduction de la fenêtre.");
        }
        app->layout();
        return 0;
    case WM_GETMINMAXINFO: {
        auto limits = reinterpret_cast<MINMAXINFO*>(lparam);
        limits->ptMinTrackSize.x = app->px(650);
        limits->ptMinTrackSize.y = app->px(505);
        return 0;
    }
    case WM_DPICHANGED: {
        app->dpi = HIWORD(wparam);
        app->update_font();
        auto rect = reinterpret_cast<RECT*>(lparam);
        SetWindowPos(window, nullptr, rect->left, rect->top, rect->right - rect->left, rect->bottom - rect->top,
            SWP_NOZORDER | SWP_NOACTIVATE);
        app->layout();
        return 0;
    }
    case WM_SETTINGCHANGE:
        app->update_font();
        break;
    case WM_COMMAND:
        switch (LOWORD(wparam)) {
        case New: app->new_blank(); return 0;
        case NewFolder: app->change_folder_metadata(NewFolder); return 0;
        case FolderActions: app->show_folder_actions(); return 0;
        case MoveNote: app->move_current_note(); return 0;
        case RenameNote: app->rename_note(); return 0;
        case RenameFolder: app->change_folder_metadata(RenameFolder); return 0;
        case Dictate: app->start_or_stop(); return 0;
        case Save: if (!app->masked) app->save_note(true); return 0;
        case Privacy: app->toggle_privacy(); return 0;
        case Vocabulary:
            if (app->phase == Phase::idle && !app->masked && !app->session_locked) {
                doct::show_catalogue(window, app->runtime);
            }
            return 0;
        case Library:
            if (HIWORD(wparam) == LBN_SELCHANGE) app->change_note();
            return 0;
        case SearchText:
            if (HIWORD(wparam) == EN_CHANGE) app->search_changed();
            return 0;
        case SearchAll:
            if (HIWORD(wparam) == BN_CLICKED && app->can_organize()) app->reload_library();
            return 0;
        case SortBy:
            if (HIWORD(wparam) == CBN_SELCHANGE && app->can_organize()) app->reload_library();
            return 0;
        case Title:
        case Body:
            if (HIWORD(wparam) == EN_CHANGE) app->mark_dirty();
            return 0;
        }
        break;
    case WM_NOTIFY: {
        const auto header = reinterpret_cast<const NMHDR*>(lparam);
        if (header && header->hwndFrom == app->folder_tree && header->code == static_cast<UINT>(TVN_SELCHANGEDW)) {
            const auto change = reinterpret_cast<const NMTREEVIEWW*>(lparam);
            if (change->itemNew.hItem) app->change_folder(change->itemNew.lParam);
            return 0;
        }
        break;
    }
    case WM_TIMER:
        if (wparam == SaveTimer) {
            app->save_note();
            return 0;
        }
        if (wparam == SearchTimer) {
            KillTimer(window, SearchTimer);
            if (app->can_organize()) app->reload_library();
            else if (app->search_pending && app->active_dialog) SetTimer(window, SearchTimer, SearchDelayMs, nullptr);
            return 0;
        }
        break;
    case EngineMessage:
        app->drain_engine();
        return 0;
    case WM_WTSSESSION_CHANGE:
        if (wparam == WTS_SESSION_LOCK || wparam == WTS_SESSION_LOGOFF || wparam == WTS_CONSOLE_DISCONNECT
                || wparam == WTS_REMOTE_DISCONNECT) {
            app->session_locked = true;
            app->conceal(L"Micro coupé · Session interrompue. La dictée ne reprend pas seule.");
        } else if (wparam == WTS_SESSION_UNLOCK || wparam == WTS_CONSOLE_CONNECT || wparam == WTS_REMOTE_CONNECT) {
            app->session_locked = false;
            app->update_controls();
        }
        return 0;
    case WM_POWERBROADCAST:
        if (wparam == PBT_APMSUSPEND || wparam == PBT_APMRESUMEAUTOMATIC || wparam == PBT_APMRESUMESUSPEND) {
            app->conceal(L"Micro coupé · Mise en veille. La dictée ne reprend pas seule.");
        }
        return TRUE;
    case WM_QUERYENDSESSION:
        app->conceal(L"Micro coupé · Fin de session.");
        return !app->dirty;
    case WM_ENDSESSION:
        if (wparam) app->shutdown();
        return 0;
    case WM_CLOSE:
        app->close();
        return 0;
    case WM_DESTROY:
        app->shutdown();
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

bool shortcut(App& app, const MSG& message) {
    if (message.message != WM_KEYDOWN || !(message.hwnd == app.window || IsChild(app.window, message.hwnd))) return false;
    const bool ctrl = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
    const bool alt = (GetKeyState(VK_MENU) & 0x8000) != 0;
    const bool shift = (GetKeyState(VK_SHIFT) & 0x8000) != 0;
    if (alt) return false;
    int command = 0;
    if (!ctrl && !shift && message.wParam == VK_F9) command = Dictate;
    if (!ctrl && !shift && message.wParam == VK_F2 && message.hwnd == app.folder_tree) command = RenameFolder;
    if (!ctrl && !shift && message.wParam == VK_F2 && message.hwnd == app.library) command = RenameNote;
    if (ctrl && message.wParam == 'N') command = shift ? NewFolder : New;
    if (ctrl && !shift && message.wParam == 'S') command = Save;
    if (ctrl && !shift && message.wParam == 'M') command = Privacy;
    if (ctrl && !shift && message.wParam == 'F' && app.can_organize()) {
        SetFocus(app.search_text);
        SendMessageW(app.search_text, EM_SETSEL, 0, -1);
        return true;
    }
    if (!command) return false;
    if ((static_cast<ULONG_PTR>(message.lParam) & (ULONG_PTR{1} << 30)) == 0) {
        SendMessageW(app.window, WM_COMMAND, MAKEWPARAM(command, 0), 0);
    }
    return true;
}
} // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int show) {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    INITCOMMONCONTROLSEX controls{sizeof(controls), ICC_TREEVIEW_CLASSES | ICC_STANDARD_CLASSES};
    if (!InitCommonControlsEx(&controls)) return 1;
    App app;
    app.instance = instance;
    WNDCLASSEXW registration{};
    registration.cbSize = sizeof(registration);
    registration.lpfnWndProc = window_proc;
    registration.hInstance = instance;
    registration.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(1));
    if (!registration.hIcon) registration.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    registration.hIconSm = registration.hIcon;
    registration.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    registration.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
    registration.lpszClassName = WindowClass;
    if (!RegisterClassExW(&registration)) return 1;
    const int dpi = static_cast<int>(GetDpiForSystem());
    RECT work{};
    const bool have_work_area = SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0) != FALSE;
    const int start_width = have_work_area ? std::min(MulDiv(1010, dpi, 96), static_cast<int>(work.right - work.left))
                                          : MulDiv(1010, dpi, 96);
    const int start_height = have_work_area ? std::min(MulDiv(680, dpi, 96), static_cast<int>(work.bottom - work.top))
                                           : MulDiv(680, dpi, 96);
    HWND window = CreateWindowExW(WS_EX_CONTROLPARENT, WindowClass, L"NoteVive · Prototype",
        WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN, CW_USEDEFAULT, CW_USEDEFAULT,
        start_width, start_height, nullptr, nullptr, instance, &app);
    if (!window) return 1;
    // Best-effort suppression of supported screen-capture paths; not a substitute for masking/lock.
    SetWindowDisplayAffinity(window, 0x11); // WDA_EXCLUDEFROMCAPTURE
    ShowWindow(window, show);
    UpdateWindow(window);
    if (app.store_ready) SetFocus(app.body);
    MSG message{};
    int result;
    while ((result = GetMessageW(&message, nullptr, 0, 0)) > 0) {
        if (!shortcut(app, message) && !IsDialogMessageW(window, &message)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
    if (result < 0 && IsWindow(window)) {
        app.save_note();
        app.shutdown();
        DestroyWindow(window);
    }
    return result < 0 ? 1 : static_cast<int>(message.wParam);
}
