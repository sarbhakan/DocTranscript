// Native probe for a disposable interactive Windows desktop. With no flags
// it never changes the clipboard. Does not start the app or use a microphone.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "external_target.h"

#include <exdisp.h>
#include <ole2.h>
#include <servprov.h>
#include <shldisp.h>
#include <shlobj.h>
#include <shlguid.h>

#include <cstdio>
#include <cwchar>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using doct::external::Result;
using doct::external::Target;
constexpr wchar_t kWindow[] = L"NoteViveExternalProbe";
constexpr UINT kFocus = WM_APP + 31;
constexpr int kFirst = 10, kSecond = 11, kPassword = 12, kReadonly = 13, kAnsi = 14;

void require(bool found, const char* description) {
    if (!found) throw std::runtime_error(description);
}
HWND field(HWND window, int id) { return GetDlgItem(window, id); }
void pump() {
    MSG event{};
    while (PeekMessageW(&event, nullptr, 0, 0, PM_REMOVE)) {
        TranslateMessage(&event);
        DispatchMessageW(&event);
    }
}
template<class F> bool within(F condition, DWORD ms = 4500) {
    const ULONGLONG deadline = GetTickCount64() + ms;
    do {
        pump();
        if (condition()) return true;
        Sleep(10);
    } while (GetTickCount64() < deadline);
    return false;
}
LRESULT CALLBACK child_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == kFocus) {
        if (GetForegroundWindow() != window) SetForegroundWindow(window);
        SetFocus(field(window, static_cast<int>(wparam)));
        return 0;
    }
    if (message == WM_CLOSE) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(window, message, wparam, lparam);
}
HWND panel(const wchar_t* title, HINSTANCE instance, int left) {
    HWND window = CreateWindowW(kWindow, title, WS_OVERLAPPEDWINDOW, left, 60, 400, 260,
                                  nullptr, nullptr, instance, nullptr);
    require(window, "create probe window");
    const auto create = [&](int id, DWORD extra_style) {
        const auto menu = reinterpret_cast<HMENU>(static_cast<INT_PTR>(id));
        const int y = 10 + (id - kFirst) * 33;
        const DWORD style = WS_CHILD | WS_VISIBLE | WS_BORDER | ES_AUTOHSCROLL | extra_style;
        HWND edit = id == kAnsi ? CreateWindowA("EDIT", "ab", style, 10, y, 340, 28, window, menu, instance, nullptr)
                                 : CreateWindowW(L"EDIT", L"ab", style, 10, y, 340, 28, window, menu, instance, nullptr);
        require(edit, "create probe field");
        SendMessageW(edit, EM_SETSEL, 1, 1); // caret between a and b
    };
    create(kFirst, 0);
    create(kSecond, 0);
    create(kPassword, ES_PASSWORD);
    create(kReadonly, ES_READONLY);
    create(kAnsi, 0);
    ShowWindow(window, SW_SHOWNOACTIVATE);
    return window;
}

int child(const std::wstring& id) {
    const HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSW clas{};
    clas.lpfnWndProc = child_proc;
    clas.hInstance = instance;
    clas.lpszClassName = kWindow;
    require(RegisterClassW(&clas), "register probe class");
    const HWND first = panel((id + L" first").c_str(), instance, 60);
    panel((id + L" second").c_str(), instance, 480);
    PostMessageW(first, kFocus, kFirst, 0);
    MSG event{};
    while (GetMessageW(&event, nullptr, 0, 0) > 0) {
        TranslateMessage(&event);
        DispatchMessageW(&event);
    }
    return 0;
}

struct Child {
    HANDLE process = nullptr;
    HWND first = nullptr;
    ~Child() {
        if (!process) return;
        if (first) PostMessageW(first, WM_CLOSE, 0, 0);
        if (WaitForSingleObject(process, 1000) == WAIT_TIMEOUT) TerminateProcess(process, 1);
        CloseHandle(process);
    }
};
HWND find(const std::wstring& name, DWORD pid) {
    HWND hwnd = FindWindowW(kWindow, name.c_str());
    DWORD actual = 0;
    return hwnd && GetWindowThreadProcessId(hwnd, &actual) && actual == pid ? hwnd : nullptr;
}
bool focus(HWND window, int id) {
    require(PostMessageW(window, kFocus, id, 0), "request focus of isolated fixture");
    return within([&] {
        GUITHREADINFO gui{};
        gui.cbSize = sizeof(gui);
        return GetForegroundWindow() == window && GetGUIThreadInfo(GetWindowThreadProcessId(window, nullptr), &gui) &&
            gui.hwndFocus == field(window, id);
    }, 2000);
}
void token_environment(const char* name, HANDLE process) {
    HANDLE token = nullptr;
    DWORD bytes = 0;
    TOKEN_ELEVATION elevation{};
    std::vector<BYTE> level;
    if (process && OpenProcessToken(process, TOKEN_QUERY, &token)) {
        GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &bytes);
        GetTokenInformation(token, TokenIntegrityLevel, nullptr, 0, &bytes);
        if (bytes && bytes <= 4096) {
            level.resize(bytes);
            if (!GetTokenInformation(token, TokenIntegrityLevel, level.data(), bytes, &bytes)) level.clear();
        }
        CloseHandle(token);
    }
    DWORD integrity = 0;
    if (!level.empty()) {
        auto sid = reinterpret_cast<TOKEN_MANDATORY_LABEL*>(level.data())->Label.Sid;
        if (IsValidSid(sid) && *GetSidSubAuthorityCount(sid))
            integrity = *GetSidSubAuthority(sid, *GetSidSubAuthorityCount(sid) - 1);
    }
    std::fprintf(stderr, "%s integrity=0x%04lx elevated=%lu\n", name,
                 static_cast<unsigned long>(integrity), static_cast<unsigned long>(elevation.TokenIsElevated));
}
int environment() {
    token_environment("probe", GetCurrentProcess());
    DWORD shell_pid = 0;
    const auto shell = GetShellWindow();
    if (shell) GetWindowThreadProcessId(shell, &shell_pid);
    auto process = shell_pid ? OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, shell_pid) : nullptr;
    token_environment("desktop_shell", process);
    if (process) CloseHandle(process);
    const auto input = OpenInputDesktop(0, FALSE, DESKTOP_READOBJECTS);
    if (input) CloseDesktop(input);
    std::fprintf(stderr, "input_desktop_readable=%d\n", input != nullptr);
    return 0;
}

int launch_desktop(const wchar_t* executable, const wchar_t* arguments, const wchar_t* directory) {
    // This is the documented Execute In Explorer approach. Only the separate
    // test executable has this launcher, never the product.
    const auto apartment = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(apartment)) return 1;
    IShellWindows* windows = nullptr;
    IDispatch* desktop = nullptr;
    IServiceProvider* provider = nullptr;
    IShellBrowser* browser = nullptr;
    IShellView* view = nullptr;
    IDispatch* automation = nullptr;
    IShellFolderViewDual* folder = nullptr;
    IDispatch* application = nullptr;
    IShellDispatch2* shell = nullptr;
    VARIANT location{}, empty{}, params{}, cwd{}, verb{}, show{};
    location.vt = VT_I4;
    location.lVal = CSIDL_DESKTOP;
    long hwnd = 0;
    HRESULT result = CoCreateInstance(__uuidof(ShellWindows), nullptr, CLSCTX_LOCAL_SERVER,
                                      IID_PPV_ARGS(&windows));
    if (SUCCEEDED(result)) result = windows->FindWindowSW(&location, &empty, SWC_DESKTOP,
                                                          &hwnd, SWFO_NEEDDISPATCH, &desktop);
    if (SUCCEEDED(result)) result = desktop ? desktop->QueryInterface(IID_PPV_ARGS(&provider)) : E_FAIL;
    if (SUCCEEDED(result)) result = provider->QueryService(SID_STopLevelBrowser, IID_PPV_ARGS(&browser));
    if (SUCCEEDED(result)) result = browser->QueryActiveShellView(&view);
    if (SUCCEEDED(result)) result = view->GetItemObject(SVGIO_BACKGROUND, IID_PPV_ARGS(&automation));
    if (SUCCEEDED(result)) result = automation->QueryInterface(IID_PPV_ARGS(&folder));
    if (SUCCEEDED(result)) result = folder->get_Application(&application);
    if (SUCCEEDED(result)) result = application->QueryInterface(IID_PPV_ARGS(&shell));
    if (SUCCEEDED(result)) {
        auto file = SysAllocString(executable);
        params.vt = cwd.vt = verb.vt = VT_BSTR;
        params.bstrVal = SysAllocString(arguments);
        cwd.bstrVal = SysAllocString(directory);
        verb.bstrVal = SysAllocString(L"open");
        show.vt = VT_I4;
        show.lVal = SW_HIDE;
        result = file && params.bstrVal && cwd.bstrVal && verb.bstrVal ?
            shell->ShellExecute(file, params, cwd, verb, show) : E_OUTOFMEMORY;
        SysFreeString(file);
        VariantClear(&params);
        VariantClear(&cwd);
        VariantClear(&verb);
    }
    for (auto* iface : {static_cast<IUnknown*>(shell), static_cast<IUnknown*>(application),
                        static_cast<IUnknown*>(folder), static_cast<IUnknown*>(automation),
                        static_cast<IUnknown*>(view), static_cast<IUnknown*>(browser),
                        static_cast<IUnknown*>(provider), static_cast<IUnknown*>(desktop),
                        static_cast<IUnknown*>(windows)}) {
        if (iface) iface->Release();
    }
    CoUninitialize();
    if (FAILED(result)) std::fprintf(stderr, "Explorer ordinary launch HRESULT=0x%08lx\n",
                                     static_cast<unsigned long>(result));
    return FAILED(result) ? 1 : 0;
}
std::wstring text(HWND edit) {
    // Reading the synthetic fixture, never a third-party document.
    wchar_t value[256]{};
    DWORD_PTR ignored = 0;
    require(SendMessageTimeoutW(edit, WM_GETTEXT, 256, reinterpret_cast<LPARAM>(value),
                                SMTO_ABORTIFHUNG | SMTO_BLOCK, 100, &ignored), "read isolated fixture");
    return value;
}
Result capture(Target& target, HWND owner) {
    target.reset();
    Sleep(30); // Do not race the previous native test's worker shutdown.
    pump();
    const auto status = target.capture(owner);
    if (status != Result::pending) return status;
    require(within([&] { return target.check() != Result::pending; }), "capture deadline");
    return target.check();
}
const char* result_id(Result result);

int run(bool test_clipboard) {
    const HINSTANCE instance = GetModuleHandleW(nullptr);
    HWND owner = CreateWindowExW(0, L"STATIC", L"NoteVive external test anchor", WS_POPUP,
                                 0, 0, 100, 50, nullptr, nullptr, instance, nullptr);
    require(owner, "create hidden test owner");
    const std::wstring id = L"NoteVive external test " + std::to_wstring(GetCurrentProcessId());
    std::vector<wchar_t> module(32768);
    auto count = GetModuleFileNameW(nullptr, module.data(), static_cast<DWORD>(module.size()));
    require(count && count < module.size(), "find test executable");
    std::wstring command = L"\"" + std::wstring(module.data(), count) + L"\" --child \"" + id + L"\"";
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION child_process{};
    require(CreateProcessW(module.data(), command.data(), nullptr, nullptr, FALSE, 0, nullptr, nullptr,
                           &startup, &child_process), "start isolated edit fixture");
    Child proc;
    proc.process = child_process.hProcess;
    CloseHandle(child_process.hThread);
    AllowSetForegroundWindow(child_process.dwProcessId);
    HWND second = nullptr;
    require(within([&] {
        proc.first = find(id + L" first", child_process.dwProcessId);
        second = find(id + L" second", child_process.dwProcessId);
        return proc.first && second && field(proc.first, kAnsi) && field(second, kAnsi);
    }), "probe windows missing");
    require(focus(proc.first, kFirst), "probe desktop not interactive or focus denied");
    Target target;
    const auto initial = capture(target, owner);
    if (initial != Result::ready) {
        token_environment("probe", GetCurrentProcess());
        token_environment("fixture", proc.process);
        std::fprintf(stderr, "initial_result=%s\n", result_id(initial));
    }
    require(initial == Result::ready, "ordinary Unicode edit refused");
    require(target.forward(L" é\r\n½ ") == Result::queued, "first segment was not queued");
    require(target.forward(L"négatif") == Result::queued, "second segment was not queued");
    require(within([&] { return !target.busy(); }) && target.check() == Result::inserted, "caret insertion did not finish");
    require(text(field(proc.first, kFirst)) == L"aé ½ négatifb", "Unicode, spacing, newline or ordering error");
    require(text(field(proc.first, kSecond)) == L"ab", "second field was modified");

    require(focus(proc.first, kSecond) && focus(proc.first, kFirst), "switch away and return within the same window");
    require(within([&] { return target.check() == Result::target_changed; }), "same-window focus change not latched");
    require(target.forward(L"interdit") == Result::target_changed, "target reopened after field switch");
    require(text(field(proc.first, kFirst)) == L"aé ½ négatifb", "text sent after field switch");

    require(capture(target, owner) == Result::ready, "explicit new capture after prior invalidation");
    require(focus(second, kFirst) && focus(proc.first, kFirst), "switch and return across windows");
    require(within([&] { return target.check() == Result::target_changed; }), "foreground change not latched");
    require(target.forward(L"interdit") == Result::target_changed, "target reopened after window switch");
    require(text(field(second, kFirst)) == L"ab", "other window was modified");

    require(focus(proc.first, kPassword), "password field focus");
    require(capture(target, owner) == Result::protected_field, "password field accepted");
    require(focus(proc.first, kReadonly), "read-only field focus");
    require(capture(target, owner) == Result::protected_field, "read-only field accepted");
    require(focus(proc.first, kAnsi), "ANSI field focus");
    require(capture(target, owner) == Result::protected_field, "ANSI edit accepted as Unicode");

    require(focus(proc.first, kSecond), "editable field focus");
    HWND second_field = field(proc.first, kSecond);
    SendMessageW(second_field, EM_SETSEL, 0, 1);
    require(capture(target, owner) == Result::unsupported, "existing selection would be clobbered");
    SendMessageW(second_field, EM_SETSEL, 1, 1);
    require(capture(target, owner) == Result::ready, "capture after selection removed");
    SendMessageW(second_field, EM_SETSEL, 2, 2);
    require(target.forward(L"interdit") == Result::queued && within([&] { return !target.busy(); }) &&
            target.check() == Result::target_changed, "caret move after capture not rejected");
    require(text(second_field) == L"ab", "field changed after caret move");
    target.reset();

    if (test_clipboard) {
        require(!doct::external::copy_note_text(owner, std::wstring_view(L"a\0b", 3)), "embedded NUL copied");
        require(doct::external::copy_note_text(owner, L"Essai fictif : é ½\r\nDeuxième ligne."), "explicit copy");
        require(OpenClipboard(owner), "read clipboard");
        auto value = GetClipboardData(CF_UNICODETEXT);
        const auto* unicode = value ? static_cast<const wchar_t*>(GlobalLock(value)) : nullptr;
        const UINT exclusion = RegisterClipboardFormatW(L"ExcludeClipboardContentFromMonitorProcessing");
        const bool valid = unicode && std::wcscmp(unicode, L"Essai fictif : é ½\r\nDeuxième ligne.") == 0 &&
            exclusion && IsClipboardFormatAvailable(exclusion);
        if (unicode) GlobalUnlock(value);
        EmptyClipboard();
        CloseClipboard();
        require(valid, "Unicode clipboard data or Windows exclusion marker missing");
    }
    DestroyWindow(owner);
    std::puts("Native external target probe: OK");
    return 0;
}

const char* result_id(Result result) {
    switch (result) {
    case Result::inactive: return "inactive";
    case Result::pending: return "pending";
    case Result::ready: return "ready";
    case Result::queued: return "queued";
    case Result::inserted: return "inserted";
    case Result::submitted: return "submitted";
    case Result::no_text: return "no_text";
    case Result::unsupported: return "unsupported";
    case Result::protected_field: return "protected_field";
    case Result::target_changed: return "target_changed";
    case Result::delivery_uncertain: return "delivery_uncertain";
    case Result::invalid_text: return "invalid_text";
    }
    return "unknown";
}

int edge_probe(DWORD edge_pid) {
    HWND owner = CreateWindowExW(0, L"STATIC", L"NoteVive Edge test anchor", WS_POPUP,
                                 0, 0, 100, 50, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    require(owner != nullptr, "hidden Edge anchor");
    Target target;
    // A separate interactive run launches a disposable Edge instance. Only
    // that browser PID is eligible, and the payload is fixed fictitious text.
    std::cout << "OK" << std::endl;
    for (std::string request; std::getline(std::cin, request);) {
        pump();
        if (request == "quit") break;
        Result result = Result::inactive;
        if (request == "capture") {
            require(edge_pid != 0, "expected Edge browser PID");
            result = target.capture(owner, nullptr, edge_pid);
            if (result == Result::pending) {
                require(within([&] { return target.check() != Result::pending; }), "Edge capture deadline");
                result = target.check();
            }
        } else if (request == "send") {
            result = target.forward(L"é ½");
            if (result == Result::queued) {
                require(within([&] { return !target.busy(); }), "Edge send deadline");
                result = target.check();
            }
        } else if (request == "check-change") {
            if (within([&] { return target.check() == Result::target_changed; }, 2000))
                result = Result::target_changed;
            else result = target.check();
        } else if (request == "reset") {
            target.reset();
            Sleep(350); // Allow COM event-handler removal on the one lane.
        } else if (request == "check") {
            result = target.check();
        } else throw std::runtime_error("unknown Edge probe command");
        std::cout << result_id(result) << std::endl;
    }
    DestroyWindow(owner);
    return 0;
}
} // namespace

int wmain(int argc, wchar_t** argv) {
    try {
        if (argc == 3 && std::wcscmp(argv[1], L"--child") == 0) return child(argv[2]);
        if (argc == 3 && std::wcscmp(argv[1], L"--edge-probe") == 0)
            return edge_probe(static_cast<DWORD>(std::stoul(argv[2])));
        if (argc == 2 && std::wcscmp(argv[1], L"--environment") == 0) return environment();
        if (argc == 5 && std::wcscmp(argv[1], L"--launch-from-desktop") == 0)
            return launch_desktop(argv[2], argv[3], argv[4]);
        if (argc == 1) return run(false);
        if (argc == 2 && std::wcscmp(argv[1], L"--clipboard") == 0) return run(true);
        return 2;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Native external target probe: %s\n", error.what());
        return 1;
    }
}
