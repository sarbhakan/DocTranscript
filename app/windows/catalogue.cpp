#include "catalogue.h"
#include "integrity.h"
#include "sqlite3.h"
#include "ui_theme.h"

#include <cwctype>
#include <algorithm>
#include <memory>
#include <string>
#include <vector>
#include <utility>
#include "catalogue_domains.h"

namespace doct {
namespace {
constexpr wchar_t kClass[] = L"NoteViveCatalogueWindow";
constexpr int kQuery=4101, kSearch=4102, kResult=4103, kClose=4104, kDomain=4105, kCategory=4106;
constexpr UINT kConceal = WM_APP + 418;

RECT work_bounds(HWND window) {
    MONITORINFO monitor{};
    monitor.cbSize = sizeof(monitor);
    if (GetMonitorInfoW(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST), &monitor)) return monitor.rcWork;
    RECT work{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    return work;
}

RECT fit_window(HWND monitor_window, RECT rect) {
    const auto work = work_bounds(monitor_window);
    const LONG width = std::max(1L, std::min(rect.right - rect.left, work.right - work.left));
    const LONG height = std::max(1L, std::min(rect.bottom - rect.top, work.bottom - work.top));
    rect.left = std::clamp(rect.left, work.left, std::max(work.left, work.right-width));
    rect.top = std::clamp(rect.top, work.top, std::max(work.top, work.bottom-height));
    rect.right = rect.left + width; rect.bottom = rect.top + height;
    return rect;
}

std::string utf8(const std::wstring& s) {
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()),
                                         nullptr, 0, nullptr, nullptr);
    if (size <= 0) return {};
    std::string out(size, '\0');
    WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()), out.data(), size, nullptr, nullptr);
    return out;
}

std::wstring from_utf8(const unsigned char* p) {
    if (!p) return {};
    const auto s = reinterpret_cast<const char*>(p);
    const int size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, nullptr, 0);
    if (size <= 1) return {};
    std::wstring out(size, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, out.data(), size);
    out.pop_back();
    return out;
}

std::string expression(std::wstring query) {
    wchar_t lower[200]{};
    const int n = LCMapStringEx(L"fr-FR", LCMAP_LOWERCASE, query.data(), static_cast<int>(query.size()),
                                lower, static_cast<int>(std::size(lower)), nullptr, nullptr, 0);
    if (n <= 0) return {};
    std::vector<std::wstring> tokens(1);
    for (int i = 0; i < n; ++i) {
        const wchar_t ch = lower[i];
        auto& token = tokens.back();
        if (ch == L'œ') token += L"oe";
        else if (ch == L'æ') token += L"ae";
        else {
            WORD type = 0;
            if (GetStringTypeW(CT_CTYPE1, &ch, 1, &type) && (type & (C1_ALPHA | C1_DIGIT))) token += ch;
            else if (!token.empty()) {
                if ((ch == L'\'' || ch == L'’' || ch == L'ʼ') && token.size() == 1
                    && std::wstring(L"cdjlmnst").find(token.front()) != std::wstring::npos) token.clear();
                else tokens.emplace_back();
            }
        }
        if (tokens.size() > 9) return {};
    }
    if (tokens.back().empty()) tokens.pop_back();
    if (tokens.size() > 8) return {};
    bool eligible = false;
    std::string out;
    for (const auto& token : tokens) {
        if (token.empty()) continue;
        const auto word = utf8(token);
        if (word.empty()) return {};
        if (!out.empty()) out += " AND ";
        out += '"' + word + '"';
        if (token.size() >= 2) { out += '*'; eligible = true; }
    }
    return eligible ? out : std::string{};
}

struct Catalogue {
    sqlite3* db = nullptr;
    HWND hint = nullptr, query = nullptr, search = nullptr, result = nullptr, close = nullptr;
    HWND domain_label = nullptr, category_label = nullptr, domain = nullptr, category = nullptr;
    std::vector<std::string> domains, categories;
    ui::Theme theme;
    UINT dpi = 96;
    bool privacy_closed = false;
    ~Catalogue() { if (db) sqlite3_close(db); }
};

std::wstring filter_label(std::string key) {
    for (const auto& item : kCatalogueDomainLabels) if (key == item.first) return item.second;
    const std::pair<const char*, const wchar_t*> labels[] = {
        {"medecine-generale", L"Médecine générale"}, {"anatomopathologie", L"Anatomopathologie"},
        {"biologie-medicale", L"Biologie médicale"}, {"pharmacologie", L"Pharmacologie"},
        {"maladie", L"Maladies"}, {"symptome", L"Symptômes"}, {"acte", L"Actes et techniques"},
        {"examen", L"Examens"}, {"dispositif", L"Dispositifs"}, {"produit-prestation", L"Produits et prestations"},
        {"medicament", L"Médicaments"}, {"substance", L"Substances"}, {"anatomie", L"Anatomie"},
        {"motif-plainte", L"Motifs et plaintes"}, {"diagnostic-soins-primaires", L"Diagnostics de soins primaires"},
        {"forme-pharmaceutique", L"Formes pharmaceutiques"}, {"voie-administration", L"Voies d’administration"},
        {"terme-anatomopathologique", L"Termes d’anatomopathologie"},
    };
    for (const auto& item : labels) if (key == item.first) return item.second;
    for (auto& c : key) if (c == '-' || c == '_') c = ' ';
    auto label = from_utf8(reinterpret_cast<const unsigned char*>(key.c_str()));
    if (!label.empty()) label.front() = static_cast<wchar_t>(towupper(label.front()));
    return label;
}

bool fill_filter(sqlite3* db, HWND combo, const char* sql, const wchar_t* all,
                 std::vector<std::string>& keys) {
    keys.emplace_back();
    SendMessageW(combo, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(all));
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &raw, nullptr) != SQLITE_OK) return false;
    std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> stmt(raw, sqlite3_finalize);
    int status;
    while ((status = sqlite3_step(raw)) == SQLITE_ROW) {
        const auto key = reinterpret_cast<const char*>(sqlite3_column_text(raw, 0));
        if (!key) return false;
        const auto label = filter_label(key);
        if (SendMessageW(combo, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(label.c_str())) < 0) return false;
        keys.emplace_back(key);
    }
    SendMessageW(combo, CB_SETCURSEL, 0, 0);
    return status == SQLITE_DONE;
}

std::string selected_filter(HWND combo, const std::vector<std::string>& keys) {
    const auto index = SendMessageW(combo, CB_GETCURSEL, 0, 0);
    return index >= 0 && static_cast<size_t>(index) < keys.size() ? keys[index] : std::string{};
}

std::wstring lookup(sqlite3* db, const std::wstring& query, const std::string& domain,
                    const std::string& category) {
    const auto expr = expression(query);
    if (expr.empty()) return L"Saisissez un à huit mots, dont un d’au moins deux caractères.";
    sqlite3_stmt* raw = nullptr;
    constexpr auto sql = "SELECT t.label,t.code,s.title,s.edition FROM term_fts JOIN term t ON t.id=term_fts.rowid "
                         "JOIN source s ON s.id=t.source_id WHERE term_fts MATCH ? "
                         "AND (?='' OR t.category=?) "
                         "AND (?='' OR EXISTS (SELECT 1 FROM specialty sp WHERE sp.term_id=t.id AND sp.name=?)) "
                         "ORDER BY rank,t.label,s.id,t.code LIMIT 25";
    if (sqlite3_prepare_v2(db, sql, -1, &raw, nullptr) != SQLITE_OK) return L"Le catalogue local est illisible.";
    std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> stmt(raw, sqlite3_finalize);
    if (sqlite3_bind_text(raw, 1, expr.data(), static_cast<int>(expr.size()), SQLITE_TRANSIENT) != SQLITE_OK)
        return L"La recherche a échoué.";
    for (int i = 2; i <= 5; ++i) {
        const auto& value = i < 4 ? category : domain;
        if (sqlite3_bind_text(raw, i, value.c_str(), static_cast<int>(value.size()), SQLITE_TRANSIENT) != SQLITE_OK)
            return L"La recherche a échoué.";
    }
    std::wstring out;
    int status = SQLITE_OK;
    while ((status = sqlite3_step(raw)) == SQLITE_ROW) {
        out += from_utf8(sqlite3_column_text(raw, 0)) + L"\r\n";
        out += from_utf8(sqlite3_column_text(raw, 2)) + L" · " + from_utf8(sqlite3_column_text(raw, 3));
        out += L" · " + from_utf8(sqlite3_column_text(raw, 1)) + L"\r\n\r\n";
    }
    if (status != SQLITE_DONE) return L"La recherche a échoué. Le catalogue a peut-être été modifié.";
    return out.empty() ? L"Aucun libellé trouvé avec ces filtres. Essayez « Tous les domaines » ou un mot plus court." : out;
}

HWND control(HWND window, DWORD ex, const wchar_t* kind, const wchar_t* caption, DWORD style, int id) {
    auto h = CreateWindowExW(ex, kind, caption, WS_VISIBLE | WS_CHILD | style, 0, 0, 1, 1, window,
                            reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), GetModuleHandleW(nullptr), nullptr);
    if (h) SendMessageW(h, WM_SETFONT, reinterpret_cast<WPARAM>(GetStockObject(DEFAULT_GUI_FONT)), TRUE);
    return h;
}

LRESULT CALLBACK catalogue_proc(HWND window, UINT msg, WPARAM w, LPARAM l) {
    auto p = reinterpret_cast<Catalogue*>(GetWindowLongPtrW(window, GWLP_USERDATA));
    if (msg == WM_NCCREATE) {
        p = static_cast<Catalogue*>(reinterpret_cast<CREATESTRUCTW*>(l)->lpCreateParams);
        SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(p));
    }
    if (!p) return DefWindowProcW(window, msg, w, l);
    if (msg == WM_CREATE) {
        p->dpi = GetDpiForWindow(window);
        if (!p->dpi) p->dpi = 96;
        p->theme.refresh(p->dpi);
        p->hint = control(window, 0, L"STATIC", L"Saisissez un terme, sans donnée patient.\r\nConsultation uniquement : ce glossaire ne modifie pas la dictée.", 0, 0);
        p->query = control(window, WS_EX_CLIENTEDGE, L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL, kQuery);
        p->search = control(window, 0, L"BUTTON", L"&Rechercher", WS_TABSTOP | BS_DEFPUSHBUTTON, kSearch);
        p->domain_label = control(window, 0, L"STATIC", L"&Domaine", 0, 0);
        p->domain = control(window, 0, L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL, kDomain);
        p->category_label = control(window, 0, L"STATIC", L"&Type de terme", 0, 0);
        p->category = control(window, 0, L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL, kCategory);
        p->result = control(window, WS_EX_CLIENTEDGE, L"EDIT", L"Les libellés et leurs sources apparaîtront ici.",
                            WS_TABSTOP | WS_VSCROLL | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL, kResult);
        p->close = control(window, 0, L"BUTTON", L"&Fermer", WS_TABSTOP, kClose);
        if (!p->hint || !p->query || !p->search || !p->result || !p->close || !p->domain_label ||
            !p->domain || !p->category_label || !p->category) return -1;
        if (!fill_filter(p->db, p->domain, "SELECT DISTINCT name FROM specialty ORDER BY name",
                         L"Tous les domaines", p->domains) ||
            !fill_filter(p->db, p->category, "SELECT DISTINCT category FROM term ORDER BY category",
                         L"Tous les types", p->categories)) return -1;
        SendMessageW(p->query, EM_SETLIMITTEXT, 160, 0);
        for (HWND child = GetWindow(window, GW_CHILD); child; child = GetWindow(child, GW_HWNDNEXT))
            SendMessageW(child, WM_SETFONT, reinterpret_cast<WPARAM>(p->theme.font()), TRUE);
        p->theme.release_previous_fonts();
    } else if (msg == WM_SIZE && p->close) {
        const int width = MulDiv(LOWORD(l), 96, p->dpi), height = MulDiv(HIWORD(l), 96, p->dpi);
        const auto move = [&](HWND h, int x, int y, int w, int hgt) {
            MoveWindow(h, MulDiv(x,p->dpi,96), MulDiv(y,p->dpi,96),
                       MulDiv(w,p->dpi,96), MulDiv(hgt,p->dpi,96), TRUE);
        };
        move(p->hint, 16, 13, width-32, 36);
        move(p->query, 16, 56, width-145, 29);
        move(p->search, width-120, 56, 104, 29);
        const int half = (width - 48) / 2;
        move(p->domain_label, 16, 98, half, 20);
        move(p->domain, 16, 121, half, 230);
        move(p->category_label, 32+half, 98, half, 20);
        move(p->category, 32+half, 121, half, 230);
        move(p->result, 16, 161, width-32, std::max(0, height-213));
        move(p->close, width-120, height-41, 104, 28);
    } else if (msg == WM_GETMINMAXINFO) {
        const auto work = work_bounds(window);
        reinterpret_cast<MINMAXINFO*>(l)->ptMinTrackSize = {
            std::min<LONG>(MulDiv(520,p->dpi,96), work.right-work.left),
            std::min<LONG>(MulDiv(370,p->dpi,96), work.bottom-work.top)};
    } else if (msg == WM_DPICHANGED || msg == WM_SETTINGCHANGE || msg == WM_THEMECHANGED) {
        if (msg == WM_DPICHANGED) p->dpi = HIWORD(w);
        p->theme.refresh(p->dpi);
        for (HWND child = GetWindow(window, GW_CHILD); child; child = GetWindow(child, GW_HWNDNEXT))
            SendMessageW(child, WM_SETFONT, reinterpret_cast<WPARAM>(p->theme.font()), TRUE);
        p->theme.release_previous_fonts();
        if (msg == WM_DPICHANGED) {
            const auto rect = fit_window(window, *reinterpret_cast<const RECT*>(l));
            SetWindowPos(window, nullptr, rect.left, rect.top, rect.right-rect.left,
                         rect.bottom-rect.top, SWP_NOZORDER | SWP_NOACTIVATE);
        }
        InvalidateRect(window, nullptr, TRUE);
    } else if (msg == WM_CTLCOLORSTATIC || msg == WM_CTLCOLOREDIT || msg == WM_CTLCOLORLISTBOX) {
        return reinterpret_cast<LRESULT>(p->theme.colors(reinterpret_cast<HDC>(w),
             reinterpret_cast<HWND>(l), ui::Surface::card));
    } else if (msg == WM_ERASEBKGND) {
        RECT rect{}; GetClientRect(window, &rect);
        auto dc = reinterpret_cast<HDC>(w);
        FillRect(dc, &rect, p->theme.colors(dc, window, ui::Surface::card));
        return 1;
    } else if (msg == WM_COMMAND) {
        if (LOWORD(w) == kSearch || LOWORD(w) == IDOK ||
            ((LOWORD(w) == kDomain || LOWORD(w) == kCategory) && HIWORD(w) == CBN_SELCHANGE)) {
            wchar_t query[161]{};
            GetWindowTextW(p->query, query, static_cast<int>(std::size(query)));
            try { SetWindowTextW(p->result, lookup(p->db, query, selected_filter(p->domain, p->domains),
                                                selected_filter(p->category, p->categories)).c_str()); }
            catch (...) { SetWindowTextW(p->result, L"La recherche locale a échoué."); }
        } else if (LOWORD(w) == kClose || LOWORD(w) == IDCANCEL) DestroyWindow(window);
    } else if (msg == kConceal) { p->privacy_closed = true; DestroyWindow(window); }
    else if (msg == WM_CLOSE) DestroyWindow(window);
    else return DefWindowProcW(window, msg, w, l);
    return 0;
}
}

void conceal_catalogue(HWND parent) {
    EnumThreadWindows(GetCurrentThreadId(), [](HWND candidate, LPARAM owner) -> BOOL {
        wchar_t name[64]{};
        if (GetWindow(candidate, GW_OWNER) == reinterpret_cast<HWND>(owner) &&
            GetClassNameW(candidate, name, static_cast<int>(std::size(name))) && wcscmp(name, kClass) == 0)
            SendMessageW(candidate, kConceal, 0, 0);
        return TRUE;
    }, reinterpret_cast<LPARAM>(parent));
}

void show_catalogue(HWND parent, const std::wstring& runtime_directory) {
    Catalogue p;
    const auto path = utf8(runtime_directory + L"\\catalogue.sqlite");
    if (path.empty() || !verify_catalogue_file(runtime_directory) ||
        sqlite3_open_v2(path.c_str(), &p.db, SQLITE_OPEN_READONLY | SQLITE_OPEN_PRIVATECACHE, nullptr) != SQLITE_OK) {
        MessageBoxW(parent, L"Le fichier de vocabulaire manque ou ne peut pas être lu. Réextrayez le dossier NoteVive complet.",
                    L"Vocabulaire NoteVive", MB_OK | MB_ICONINFORMATION);
        return;
    }
    sqlite3_db_config(p.db, SQLITE_DBCONFIG_TRUSTED_SCHEMA, 0, nullptr);
    sqlite3_db_config(p.db, SQLITE_DBCONFIG_DEFENSIVE, 1, nullptr);
    sqlite3_stmt* version = nullptr;
    const bool valid = sqlite3_prepare_v2(p.db, "PRAGMA user_version", -1, &version, nullptr) == SQLITE_OK &&
                       sqlite3_step(version) == SQLITE_ROW && sqlite3_column_int(version, 0) == 2;
    if (version) sqlite3_finalize(version);
    if (!valid) {
        MessageBoxW(parent, L"Cette édition du vocabulaire ne correspond pas à NoteVive.",
                    L"Vocabulaire NoteVive", MB_OK | MB_ICONINFORMATION);
        return;
    }
    WNDCLASSW wc{};
    wc.lpfnWndProc = catalogue_proc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_BTNFACE+1);
    wc.lpszClassName = kClass;
    if (!RegisterClassW(&wc) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) return;
    RECT base{}; GetWindowRect(parent, &base);
    const auto parent_dpi = GetDpiForWindow(parent);
    const UINT dpi = parent_dpi ? parent_dpi : 96;
    p.dpi = dpi;
    const LONG left = base.left + MulDiv(24,dpi,96), top = base.top + MulDiv(36,dpi,96);
    const auto fitted = fit_window(parent, {left, top, left+MulDiv(680,dpi,96), top+MulDiv(480,dpi,96)});
    const HWND popup = CreateWindowExW(WS_EX_DLGMODALFRAME | WS_EX_CONTROLPARENT, kClass,
         L"Vocabulaire médical · NoteVive", WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME,
         fitted.left, fitted.top, fitted.right-fitted.left, fitted.bottom-fitted.top,
         parent, nullptr, wc.hInstance, &p);
    if (!popup) return;
    EnableWindow(parent, FALSE);
    ShowWindow(popup, SW_SHOW);
    SetFocus(p.query);
    MSG message{};
    while (IsWindow(popup)) {
        const BOOL status = GetMessageW(&message, nullptr, 0, 0);
        if (status <= 0) {
            if (IsWindow(popup)) DestroyWindow(popup);
            if (status == 0) PostQuitMessage(static_cast<int>(message.wParam));
            break;
        }
        if (message.message == WM_KEYDOWN && (message.hwnd == popup || IsChild(popup, message.hwnd))) {
            if (message.wParam == VK_ESCAPE) { DestroyWindow(popup); continue; }
            if (message.wParam == VK_RETURN && GetFocus() == p.query) {
                SendMessageW(popup, WM_COMMAND, kSearch, 0); continue;
            }
        }
        if (!IsDialogMessageW(popup, &message)) { TranslateMessage(&message); DispatchMessageW(&message); }
    }
    if (IsWindow(parent)) {
        EnableWindow(parent, TRUE);
        if (!p.privacy_closed) SetActiveWindow(parent);
    }
}
}
