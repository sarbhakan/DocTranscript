#include "catalogue.h"
#include "integrity.h"
#include "sqlite3.h"

#include <cwctype>
#include <memory>
#include <string>
#include <vector>

namespace doct {
namespace {
constexpr wchar_t kClass[] = L"NoteViveCatalogueWindow";
constexpr int kQuery=4101, kSearch=4102, kResult=4103, kClose=4104;

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
    ~Catalogue() { if (db) sqlite3_close(db); }
};

std::wstring lookup(sqlite3* db, const std::wstring& query) {
    const auto expr = expression(query);
    if (expr.empty()) return L"Saisissez un à huit mots, dont un d’au moins deux caractères.";
    sqlite3_stmt* raw = nullptr;
    constexpr auto sql = "SELECT t.label,t.code,s.title,s.edition FROM term_fts JOIN term t ON t.id=term_fts.rowid "
                         "JOIN source s ON s.id=t.source_id WHERE term_fts MATCH ? "
                         "ORDER BY rank,t.label,s.id,t.code LIMIT 25";
    if (sqlite3_prepare_v2(db, sql, -1, &raw, nullptr) != SQLITE_OK) return L"Le catalogue local est illisible.";
    std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> stmt(raw, sqlite3_finalize);
    if (sqlite3_bind_text(raw, 1, expr.data(), static_cast<int>(expr.size()), SQLITE_TRANSIENT) != SQLITE_OK)
        return L"La recherche a échoué.";
    std::wstring out;
    int status = SQLITE_OK;
    while ((status = sqlite3_step(raw)) == SQLITE_ROW) {
        out += from_utf8(sqlite3_column_text(raw, 0)) + L"\r\n";
        out += from_utf8(sqlite3_column_text(raw, 2)) + L" · " + from_utf8(sqlite3_column_text(raw, 3));
        out += L" · " + from_utf8(sqlite3_column_text(raw, 1)) + L"\r\n\r\n";
    }
    if (status != SQLITE_DONE) return L"La recherche a échoué. Le catalogue a peut-être été modifié.";
    return out.empty() ? L"Aucun libellé trouvé." : out;
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
        p->hint = control(window, 0, L"STATIC", L"Glossaire local · Saisissez un terme, sans information patient.", 0, 0);
        p->query = control(window, WS_EX_CLIENTEDGE, L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL, kQuery);
        p->search = control(window, 0, L"BUTTON", L"&Rechercher", WS_TABSTOP | BS_DEFPUSHBUTTON, kSearch);
        p->result = control(window, WS_EX_CLIENTEDGE, L"EDIT", L"Les libellés et leurs sources apparaîtront ici.",
                            WS_TABSTOP | WS_VSCROLL | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL, kResult);
        p->close = control(window, 0, L"BUTTON", L"&Fermer", WS_TABSTOP, kClose);
        if (!p->hint || !p->query || !p->search || !p->result || !p->close) return -1;
        SendMessageW(p->query, EM_SETLIMITTEXT, 160, 0);
    } else if (msg == WM_SIZE && p->close) {
        const int width = LOWORD(l), height = HIWORD(l);
        MoveWindow(p->hint, 16, 13, width-32, 23, TRUE);
        MoveWindow(p->query, 16, 40, width-145, 29, TRUE);
        MoveWindow(p->search, width-120, 40, 104, 29, TRUE);
        MoveWindow(p->result, 16, 80, width-32, height-132, TRUE);
        MoveWindow(p->close, width-120, height-41, 104, 28, TRUE);
    } else if (msg == WM_GETMINMAXINFO) {
        reinterpret_cast<MINMAXINFO*>(l)->ptMinTrackSize = {420, 270};
    } else if (msg == WM_COMMAND) {
        if (LOWORD(w) == kSearch || LOWORD(w) == IDOK) {
            wchar_t query[161]{};
            GetWindowTextW(p->query, query, static_cast<int>(std::size(query)));
            try { SetWindowTextW(p->result, lookup(p->db, query).c_str()); }
            catch (...) { SetWindowTextW(p->result, L"La recherche locale a échoué."); }
        } else if (LOWORD(w) == kClose || LOWORD(w) == IDCANCEL) DestroyWindow(window);
    } else if (msg == WM_CLOSE) DestroyWindow(window);
    else return DefWindowProcW(window, msg, w, l);
    return 0;
}
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
    const HWND popup = CreateWindowExW(WS_EX_DLGMODALFRAME | WS_EX_CONTROLPARENT, kClass,
         L"Vocabulaire médical · NoteVive", WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME,
         base.left+24, base.top+36, 680, 430, parent, nullptr, wc.hInstance, &p);
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
    if (IsWindow(parent)) { EnableWindow(parent, TRUE); SetActiveWindow(parent); }
}
}
