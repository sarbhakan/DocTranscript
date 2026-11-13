#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <wtsapi32.h>

#include <algorithm>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
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
constexpr std::size_t TitleLimit = notes::kMaxTitle;
constexpr std::size_t TextLimit = notes::kMaxText;
constexpr wchar_t OriginalEditProc[] = L"NoteVive.OriginalEditProc";

enum Control : int {
    New = 101, Dictate, Save, Privacy, Vocabulary, Library, Title, Body, Draft,
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

std::wstring list_caption(const notes::Note& note) {
    return note.modified.size() >= 16
        ? note.modified.substr(0, 10) + L" · " + note.modified.substr(11, 5) + L" UTC  —  " + display_title(note)
        : display_title(note);
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

struct App {
    HINSTANCE instance{};
    HWND window{};
    HWND banner{}, new_note{}, dictate{}, save_button{}, privacy{}, vocab{};
    HWND library_label{}, library{}, title_label{}, title{}, body_label{}, body{}, draft_label{}, draft{};
    HWND mic_status{}, storage_status{}, masked_info{};
    HFONT font{};
    UINT dpi{96};
    notes::Store store;
    notes::Note current;
    std::vector<notes::Note> entries;
    std::mutex event_mutex;
    std::deque<doct::EngineEvent> pending_events;
    std::unique_ptr<doct::Engine> engine;
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

    HWND control(const wchar_t* klass, const wchar_t* label, DWORD style, int id = 0, DWORD ex_style = 0) const {
        return CreateWindowExW(ex_style, klass, label, WS_CHILD | WS_VISIBLE | style, 0, 0, 0, 0,
            window, id ? reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)) : nullptr, instance, nullptr);
    }

    bool create() {
        dpi = GetDpiForWindow(window);
        if (!dpi) dpi = 96;
        banner = control(L"STATIC", L"NoteVive · Prototype hors ligne — données fictives uniquement", SS_LEFT);
        new_note = control(L"BUTTON", L"&Nouvelle note", WS_TABSTOP | BS_PUSHBUTTON, New);
        dictate = control(L"BUTTON", L"&Dicter (F9)", WS_TABSTOP | BS_PUSHBUTTON, Dictate);
        save_button = control(L"BUTTON", L"&Enregistrer", WS_TABSTOP | BS_PUSHBUTTON, Save);
        privacy = control(L"BUTTON", L"&Masquer la note", WS_TABSTOP | BS_PUSHBUTTON, Privacy);
        vocab = control(L"BUTTON", L"&Vocabulaire", WS_TABSTOP | BS_PUSHBUTTON, Vocabulary);
        library_label = control(L"STATIC", L"&Notes locales (UTC)", SS_LEFT);
        library = control(L"LISTBOX", L"", WS_TABSTOP | WS_VSCROLL | LBS_NOTIFY | LBS_NOINTEGRALHEIGHT,
            Library, WS_EX_CLIENTEDGE);
        title_label = control(L"STATIC", L"&Titre", SS_LEFT);
        title = control(L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL, Title, WS_EX_CLIENTEDGE);
        body_label = control(L"STATIC", L"T&exte de la note (modifiable)", SS_LEFT);
        body = control(L"EDIT", L"", WS_TABSTOP | ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN | WS_VSCROLL,
            Body, WS_EX_CLIENTEDGE);
        draft_label = control(L"STATIC", L"Texte provisoire — peut changer ; non sauvegardé", SS_LEFT);
        draft = control(L"EDIT", L"", ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL,
            Draft, WS_EX_CLIENTEDGE);
        mic_status = control(L"STATIC", L"Micro coupé", SS_LEFT | SS_NOPREFIX);
        storage_status = control(L"STATIC", L"", SS_LEFT | SS_NOPREFIX);
        masked_info = control(L"STATIC", L"Note masquée. Réaffichez-la explicitement pour reprendre.", SS_LEFT);
        for (HWND item : controls()) if (!item) return false;
        for (HWND item : {title, body, draft}) if (!restrict_clipboard(item)) return false;
        SendMessageW(title, EM_SETLIMITTEXT, TitleLimit, 0);
        SendMessageW(body, EM_SETLIMITTEXT, TextLimit, 0);
        SendMessageW(draft, EM_SETLIMITTEXT, TextLimit, 0);
        update_font();
        runtime = runtime_path();
        wts_registered = WTSRegisterSessionNotification(window, NOTIFY_FOR_THIS_SESSION) != FALSE;
        if (!wts_registered) idle_status = L"Micro coupé · Dictée indisponible : verrouillage de session non surveillé.";
        if (runtime.empty()) idle_status = L"Micro coupé · Dossier du moteur introuvable.";
        engine = std::make_unique<doct::Engine>([this, target = window](doct::EngineEvent value) {
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
        if (store_ready) reload_library();
        else set_storage(error.empty() ? L"Stockage local indisponible." : error);
        if (store_ready && GetWindowTextLengthW(storage_status) == 0) {
            set_storage(entries.empty() ? L"Aucune note sauvegardée."
                                        : L"Brouillon vide · Choisissez une note locale pour la rouvrir.");
        }
        update_controls();
        layout();
        return true;
    }

    std::vector<HWND> controls() const {
        return {banner, new_note, dictate, save_button, privacy, vocab, library_label, library, title_label,
            title, body_label, body, draft_label, draft, mic_status, storage_status, masked_info};
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
        const int side = std::clamp(width / 3, px(145), px(290));
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
        button(new_note, 112);
        button(dictate, 154);
        button(save_button, 100);
        button(privacy, 140);
        button(vocab, 108);
        const int content_top = toolbar_y + px(72);
        const int content_bottom = height - px(34);
        const int provisional_h = std::clamp((content_bottom - content_top) / 4, px(42), px(100));
        const int provisional_top = content_bottom - provisional_h;
        move(mic_status, left, toolbar_y + px(38), right - left, px(30));
        move(library_label, left, content_top, side, px(18));
        move(library, left, content_top + px(20), side, content_bottom - content_top - px(20));
        move(title_label, edit_x, content_top, edit_w, px(18));
        move(title, edit_x, content_top + px(20), edit_w, px(28));
        move(body_label, edit_x, content_top + px(57), edit_w, px(18));
        move(body, edit_x, content_top + px(77), edit_w, provisional_top - content_top - px(105));
        move(draft_label, edit_x, provisional_top - px(21), edit_w, px(20));
        move(draft, edit_x, provisional_top, edit_w, provisional_h);
        move(storage_status, left, height - px(26), right - left, px(22));
        move(masked_info, left, content_top + px(36), right - left, px(40));
    }

    void set_storage(const std::wstring& label) const {
        SetWindowTextW(storage_status, label.c_str());
    }

    void update_controls() {
        const bool idle = phase == Phase::idle;
        const bool visible = !masked && !session_locked;
        for (HWND item : {new_note, dictate, save_button, vocab, library_label, library, title_label,
                           title, body_label, body, draft_label, draft, storage_status}) {
            ShowWindow(item, visible ? SW_SHOW : SW_HIDE);
        }
        ShowWindow(masked_info, visible ? SW_HIDE : SW_SHOW);
        EnableWindow(privacy, !session_locked);
        SetWindowTextW(privacy, visible ? L"&Masquer la note" : L"&Réafficher la note");
        EnableWindow(new_note, idle && store_ready);
        EnableWindow(library, idle && store_ready);
        EnableWindow(save_button, store_ready);
        EnableWindow(vocab, idle && !runtime.empty());
        EnableWindow(title, store_ready);
        EnableWindow(body, store_ready);
        EnableWindow(dictate, store_ready && wts_registered && !runtime.empty() && !microphone_unconfirmed
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
            status = L"Micro ouvert · Dictée en cours.";
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
        if (microphone_unconfirmed) status = L"Arrêt du microphone non confirmé. Fermez l’application.";
        SetWindowTextW(dictate, button_text);
        SetWindowTextW(mic_status, status);
    }

    void choose_current() const {
        auto found = std::find_if(entries.begin(), entries.end(), [&](const notes::Note& item) { return item.id == current.id; });
        const auto index = found == entries.end() ? LB_ERR : static_cast<LRESULT>(found - entries.begin());
        SendMessageW(library, LB_SETCURSEL, static_cast<WPARAM>(index), 0);
    }

    void reload_library() {
        std::wstring error;
        std::vector<notes::Note> loaded;
        const bool ok = store.List(loaded, error);
        SendMessageW(library, WM_SETREDRAW, FALSE, 0);
        SendMessageW(library, LB_RESETCONTENT, 0, 0);
        entries.clear();
        for (auto& item : loaded) {
            const std::wstring caption = list_caption(item);
            if (SendMessageW(library, LB_ADDSTRING, 0, reinterpret_cast<LPARAM>(caption.c_str())) < 0) break;
            entries.push_back(std::move(item));
        }
        choose_current();
        SendMessageW(library, WM_SETREDRAW, TRUE, 0);
        InvalidateRect(library, nullptr, TRUE);
        const bool library_degraded = !ok || entries.size() != loaded.size();
        SetWindowTextW(library_label, library_degraded ? L"&Notes locales (liste partielle)" : L"&Notes locales (UTC)");
        if (library_degraded) set_storage(error.empty() ? L"Certaines notes locales ne sont pas lisibles." : error);
    }

    void update_saved_entry() {
        auto found = std::find_if(entries.begin(), entries.end(), [&](const notes::Note& item) { return item.id == current.id; });
        if (found != entries.end()) {
            SendMessageW(library, LB_DELETESTRING, static_cast<WPARAM>(found - entries.begin()), 0);
            entries.erase(found);
        }
        notes::Note entry;
        entry.id = current.id;
        entry.title = current.title;
        entry.created = current.created;
        entry.modified = current.modified;
        const auto order = [](const notes::Note& left, const notes::Note& right) {
            return left.modified > right.modified || (left.modified == right.modified && left.id < right.id);
        };
        const auto where = std::lower_bound(entries.begin(), entries.end(), entry, order);
        const auto caption = list_caption(entry);
        const auto result = SendMessageW(library, LB_INSERTSTRING, static_cast<WPARAM>(where - entries.begin()),
            reinterpret_cast<LPARAM>(caption.c_str()));
        if (result >= 0) entries.insert(where, std::move(entry));
        else {
            SetWindowTextW(library_label, L"&Notes locales (liste partielle)");
        }
        choose_current();
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
        set_storage(current.id.empty() ? L"Brouillon vide · La sauvegarde commence après la première modification."
                                      : L"Note chargée · Modifications sauvegardées localement.");
        choose_current();
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
        const auto index = SendMessageW(library, LB_GETCURSEL, 0, 0);
        if (index < 0 || static_cast<std::size_t>(index) >= entries.size()) return;
        // Saving refreshes the list; capture the opaque ID before doing it.
        const auto id = entries[static_cast<std::size_t>(index)].id;
        if (phase != Phase::idle || masked || id == current.id || !save_note()) {
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
        if (!store.Save(pending, error)) {
            set_storage(error.empty() ? L"Sauvegarde impossible · Le texte reste dans cet éditeur." : error);
            if (!recovery || pending.id.empty() || masked || session_locked || phase != Phase::idle) return false;
            if (MessageBoxW(window, L"Cette note n’a pas pu être mise à jour. Enregistrer son contenu dans une nouvelle note ?\n\n"
                    L"La version précédente restera intacte.", L"NoteVive", MB_YESNO | MB_DEFBUTTON2 | MB_ICONQUESTION) != IDYES) {
                return false;
            }
            if (masked || session_locked) return false;
            pending.id.clear();
            pending.created.clear();
            pending.modified.clear();
            if (!store.Save(pending, error)) {
                set_storage(error.empty() ? L"Impossible de sauvegarder la copie." : error);
                return false;
            }
        }
        current = std::move(pending);
        dirty = false;
        set_storage(L"Brouillon sauvegardé localement · À relire.");
        update_saved_entry();
        return true;
    }

    void new_blank() {
        if (phase != Phase::idle || masked || session_locked || !store_ready || !save_note()) return;
        place_note({});
        SetFocus(body);
    }

    void start_or_stop() {
        if (session_locked || masked || shutting_down || !store_ready || !wts_registered || runtime.empty()
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
        cancel_capture(reason);
        save_note();
        if (!session_locked) SetFocus(privacy);
    }

    void toggle_privacy() {
        if (session_locked) return;
        if (masked) {
            masked = false;
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
            if (!blocked_generation && !masked && !session_locked) append_final(event.text);
            SetWindowTextW(draft, L"");
            return;
        case doct::EngineEventKind::capture_stopped:
            captured = false;
            phase = Phase::finalizing;
            break;
        case doct::EngineEventKind::stopped:
            phase = Phase::idle;
            captured = false;
            idle_status = interrupt_status.empty() ? L"Micro coupé · Dictée terminée. Relisez le texte." : interrupt_status;
            SetWindowTextW(draft, L"");
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
        cancel_capture(L"Micro coupé · Fermeture interrompue si la sauvegarde échoue.");
        if (!save_note(true)) {
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
        limits->ptMinTrackSize.x = app->px(460);
        limits->ptMinTrackSize.y = app->px(385);
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
        case Title:
        case Body:
            if (HIWORD(wparam) == EN_CHANGE) app->mark_dirty();
            return 0;
        }
        break;
    case WM_TIMER:
        if (wparam == SaveTimer) {
            app->save_note();
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
    if (alt || shift) return false;
    int command = 0;
    if (!ctrl && message.wParam == VK_F9) command = Dictate;
    if (ctrl && message.wParam == 'N') command = New;
    if (ctrl && message.wParam == 'S') command = Save;
    if (ctrl && message.wParam == 'M') command = Privacy;
    if (!command) return false;
    if ((static_cast<ULONG_PTR>(message.lParam) & (ULONG_PTR{1} << 30)) == 0) {
        SendMessageW(app.window, WM_COMMAND, MAKEWPARAM(command, 0), 0);
    }
    return true;
}
} // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int show) {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
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
    const int start_width = have_work_area ? std::min(MulDiv(940, dpi, 96), static_cast<int>(work.right - work.left))
                                          : MulDiv(940, dpi, 96);
    const int start_height = have_work_area ? std::min(MulDiv(615, dpi, 96), static_cast<int>(work.bottom - work.top))
                                           : MulDiv(615, dpi, 96);
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
