// Native probe for a disposable interactive Windows desktop. With no flags
// it never changes the clipboard. Does not start the app or use a microphone.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "external_target.h"

#include <aclapi.h>
#include <bcrypt.h>
#include <lm.h>
#include <objbase.h>
#include <sddl.h>
#include <securityappcontainer.h>
#include <userenv.h>
#include <winternl.h>
#include <wtsapi32.h>

#include <cstdio>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
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

bool ordinary_token() {
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return false;
    DWORD bytes = 0;
    TOKEN_ELEVATION elevation{};
    const bool unraised = GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &bytes) &&
        !elevation.TokenIsElevated;
    GetTokenInformation(token, TokenIntegrityLevel, nullptr, 0, &bytes);
    std::vector<BYTE> info(bytes && bytes <= 4096 ? bytes : 0);
    const bool read = !info.empty() && GetTokenInformation(token, TokenIntegrityLevel, info.data(), bytes, &bytes);
    CloseHandle(token);
    if (!unraised || !read) return false;
    auto sid = reinterpret_cast<TOKEN_MANDATORY_LABEL*>(info.data())->Label.Sid;
    if (!IsValidSid(sid) || !*GetSidSubAuthorityCount(sid)) return false;
    const auto integrity = *GetSidSubAuthority(sid, *GetSidSubAuthorityCount(sid) - 1);
    return integrity >= SECURITY_MANDATORY_MEDIUM_RID && integrity < SECURITY_MANDATORY_HIGH_RID;
}

struct LocalHandle {
    HANDLE value = nullptr;
    ~LocalHandle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
};

DWORD report_session(const char* role, DWORD pid, HANDLE process) {
    DWORD session = UINT32_MAX, token_session = UINT32_MAX, length = 0;
    ProcessIdToSessionId(pid, &session);
    LocalHandle token;
    if (OpenProcessToken(process, TOKEN_QUERY, &token.value))
        GetTokenInformation(token.value, TokenSessionId, &token_session, sizeof(token_session), &length);
    std::printf("%s process_session=%lu token_session=%lu\n", role,
                static_cast<unsigned long>(session), static_cast<unsigned long>(token_session));
    return session;
}

struct NamespaceObservation {
    NTSTATUS minimum = 0, with_subdirectory = 0;
    DWORD bare_mutex = ERROR_GEN_FAILURE, local_mutex = ERROR_GEN_FAILURE;
    bool have_directory_api = false, normal_logon_access = false;
};
NamespaceObservation observe_namespace(DWORD session, bool check_logon = false);
void observe_renderer_objects(DWORD session);
bool observe_lowbox_creation(DWORD session);
void observe_appcontainer_links(DWORD session);
bool token_part(HANDLE token, TOKEN_INFORMATION_CLASS kind, std::vector<BYTE>& value);

bool disposable_recipe_account() {
    wchar_t name[64]{};
    DWORD size = 64;
    if (!GetUserNameW(name, &size) || size != 20 || std::wcsncmp(name, L"nvrecipe-", 9) != 0)
        return false;
    return std::wcsspn(name + 9, L"0123456789abcdef") == 10;
}

void observe_self_token_access() {
    // Request handles to this ephemeral account's own token. No privilege is
    // enabled and any duplicate is closed without use in a process or thread.
    struct Check { const char* name; DWORD mask; };
    constexpr Check checks[] = {{"query_duplicate", TOKEN_QUERY | TOKEN_DUPLICATE},
        {"assign_primary", TOKEN_ASSIGN_PRIMARY}, {"assignable", TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY},
        {"all", TOKEN_ALL_ACCESS}};
    for (const auto& check : checks) {
        LocalHandle opened;
        const DWORD result = OpenProcessToken(GetCurrentProcess(), check.mask, &opened.value) ?
            ERROR_SUCCESS : GetLastError();
        std::printf("Edge standard self token open %s: win32=%lu\n",
                    check.name, static_cast<unsigned long>(result));
    }
    LocalHandle original;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_DUPLICATE, &original.value)) return;
    for (const auto& check : checks) {
        LocalHandle copy;
        const DWORD result = DuplicateTokenEx(original.value, check.mask, nullptr,
            SecurityImpersonation, TokenPrimary, &copy.value) ? ERROR_SUCCESS : GetLastError();
        std::printf("Edge standard self token duplicate %s: win32=%lu\n",
                    check.name, static_cast<unsigned long>(result));
    }
}

DWORD launch_in_test_job(bool ui_limits) {
    // Chromium passes its renderer job in this process startup attribute.
    // The two arms change only the UI limits; the test executable never runs.
    LocalHandle job{CreateJobObjectW(nullptr, nullptr)};
    require(job.value, "job control: create inner job");
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION cleanup{};
    cleanup.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    require(SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &cleanup, sizeof(cleanup)),
            "job control: configure inner job cleanup");
    if (ui_limits) {
        JOBOBJECT_BASIC_UI_RESTRICTIONS restrictions{JOB_OBJECT_UILIMIT_HANDLES};
        require(SetInformationJobObject(job.value, JobObjectBasicUIRestrictions, &restrictions, sizeof(restrictions)),
                "job control: configure inner job UI limits");
    }
    wchar_t executable[MAX_PATH]{};
    const auto length = GetModuleFileNameW(nullptr, executable, MAX_PATH);
    require(length && length < MAX_PATH, "job control: executable path");
    SIZE_T size = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &size);
    require(size && size <= 65536, "job control: attribute size");
    std::vector<BYTE> storage(size);
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.lpAttributeList = reinterpret_cast<PPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
    require(InitializeProcThreadAttributeList(startup.lpAttributeList, 1, 0, &size),
            "job control: initialize attributes");
    if (!UpdateProcThreadAttribute(startup.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST,
                                   &job.value, sizeof(job.value), nullptr, nullptr)) {
        DeleteProcThreadAttributeList(startup.lpAttributeList);
        throw std::runtime_error("job control: set inner job attribute");
    }
    PROCESS_INFORMATION child{};
    const BOOL launched = CreateProcessW(executable, nullptr, nullptr, nullptr, FALSE,
        CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT,
        nullptr, nullptr, &startup.StartupInfo, &child);
    const DWORD error = launched ? ERROR_SUCCESS : GetLastError();
    DeleteProcThreadAttributeList(startup.lpAttributeList);
    if (launched) {
        LocalHandle process{child.hProcess}, thread{child.hThread};
        require(TerminateProcess(process.value, 0) && WaitForSingleObject(process.value, 1000) == WAIT_OBJECT_0,
                "job control: stop the suspended process");
    }
    return error;
}

int edge_startup_preflight() {
    if (!ordinary_token()) return 1;
    const auto session = report_session("edge_recipe", GetCurrentProcessId(), GetCurrentProcess());
    observe_self_token_access();
    BOOL in_job = FALSE;
    require(IsProcessInJob(GetCurrentProcess(), nullptr, &in_job), "read Edge recipe job membership");
    const DWORD result = launch_in_test_job(true);
    std::printf("Edge startup job: inherited=%d ui_limited_job_launch=%lu\n",
                in_job != FALSE, static_cast<unsigned long>(result));
    if (!in_job && result != ERROR_SUCCESS) return 1;
    observe_renderer_objects(session);
    observe_appcontainer_links(session);
    // The suspended child gets its own profile environment, not the
    // launcher's CI variables. Its random account name selects this probe.
    const bool check_logon = disposable_recipe_account();
    const auto names = observe_namespace(session, check_logon);
    const bool mutex = names.local_mutex == ERROR_SUCCESS;
    if (check_logon && !names.normal_logon_access) {
        std::fputs("The actual disposable login did not receive the witnessed directory access.\n", stderr);
        return 1;
    }
    const bool lowbox = observe_lowbox_creation(session);
    std::printf("Edge broker preflight: local_mutex=%d synthetic_lowbox=%d\n", mutex, lowbox);
    // An unregistered synthetic package does not reproduce Edge's package
    // and capabilities. Only the actual browser may decide that recipe.
    if (!mutex) return 1;
    return lowbox ? 0 : 2;
}

bool hosted_recipe() {
    const auto expected = [](const wchar_t* name, const wchar_t* value) {
        wchar_t buffer[32]{};
        const DWORD size = GetEnvironmentVariableW(name, buffer, 32);
        return size && size < 32 && std::wcscmp(buffer, value) == 0;
    };
    return expected(L"GITHUB_ACTIONS", L"true") && expected(L"RUNNER_ENVIRONMENT", L"github-hosted");
}

// Hosted Edge recipe only. A secondary logon in the runner's desktop session
// has no default entry permitting creation of named objects in that session.
// This guard adds a non-inherited entry for the verified recipe identity on one
// directory and restores the original DACL after the process job is stopped.
struct RecipeNamespace {
    // NtOpenDirectoryObject's documented DIRECTORY_QUERY / TRAVERSE / CREATE_OBJECT.
    static constexpr ACCESS_MASK recipe_access = 0x0001 | 0x0002 | 0x0004;
    // Some Win32-compatible implementations additionally request this right
    // when obtaining the namespace handle, regardless of the object type.
    static constexpr ACCESS_MASK with_subdirectory = recipe_access | 0x0008;
    // The hosted Windows trace of CreateAppContainerToken independently
    // showed an open of BaseNamedObjects with exactly this access.
    static constexpr ACCESS_MASK lowbox_read = READ_CONTROL | 0x0001 | 0x0002;
    // Windows duplicates the child directory with this exact mask; accept
    // it only as a copy of an existing direct ACE for the host logon.
    static constexpr ACCESS_MASK normal_logon_rights = STANDARD_RIGHTS_REQUIRED | with_subdirectory;
    static_assert(normal_logon_rights == 0x000f000f);
    static constexpr NTSTATUS denied = static_cast<NTSTATUS>(0xc0000022u);
    using OpenDirectory = NTSTATUS (NTAPI*)(PHANDLE, ACCESS_MASK, POBJECT_ATTRIBUTES);
    enum class Kind { base, app_container };
    const Kind kind;
    LocalHandle directory;
    std::vector<BYTE> original;
    bool changed = false;

    explicit RecipeNamespace(Kind selected = Kind::base) : kind(selected) {}
    ~RecipeNamespace() {
        if (!restore()) std::fprintf(stderr, "Unable to restore the session %s ACL.\n", label());
    }
    const char* label() const { return kind == Kind::base ? "BaseNamedObjects" : "AppContainerNamedObjects"; }
    const wchar_t* leaf() const { return kind == Kind::base ? L"BaseNamedObjects" : L"AppContainerNamedObjects"; }

    bool read_dacl(std::vector<BYTE>& output) const {
        DWORD needed = 0;
        GetKernelObjectSecurity(directory.value, DACL_SECURITY_INFORMATION, nullptr, 0, &needed);
        if (!needed || needed > 65536) return false;
        output.resize(needed);
        return GetKernelObjectSecurity(directory.value, DACL_SECURITY_INFORMATION,
                                       output.data(), needed, &needed) != FALSE;
    }

    bool restore() {
        if (changed) {
            if (!SetKernelObjectSecurity(directory.value, DACL_SECURITY_INFORMATION, original.data())) return false;
            std::vector<BYTE> restored;
            if (!read_dacl(restored)) return false;
            SECURITY_DESCRIPTOR_CONTROL old_flags{}, new_flags{};
            constexpr SECURITY_DESCRIPTOR_CONTROL flags =
                SE_DACL_PRESENT | SE_DACL_DEFAULTED | SE_DACL_PROTECTED |
                SE_DACL_AUTO_INHERITED | SE_DACL_AUTO_INHERIT_REQ;
            DWORD revision = 0;
            BOOL present = FALSE, defaulted = FALSE;
            PACL old = nullptr, actual = nullptr;
            if (!GetSecurityDescriptorControl(original.data(), &old_flags, &revision) ||
                !GetSecurityDescriptorControl(restored.data(), &new_flags, &revision) ||
                (old_flags & flags) != (new_flags & flags) ||
                !GetSecurityDescriptorDacl(original.data(), &present, &old, &defaulted) || !present || !old ||
                !GetSecurityDescriptorDacl(restored.data(), &present, &actual, &defaulted) || !present || !actual ||
                old->AclSize != actual->AclSize || std::memcmp(old, actual, old->AclSize) != 0) {
                std::fprintf(stderr, "Restored session %s DACL differs from the saved ACL or flags.\n", label());
                return false;
            }
            changed = false;
            std::fprintf(stderr, "Original session named-object DACL restored and verified (%s).\n", label());
        }
        return true;
    }

    static NTSTATUS open(OpenDirectory call, DWORD session, ACCESS_MASK access, HANDLE& handle,
                         const wchar_t* name_leaf = L"BaseNamedObjects") {
        std::wstring path = L"\\Sessions\\" + std::to_wstring(session) + L"\\" + name_leaf;
        UNICODE_STRING name{};
        name.Length = static_cast<USHORT>(path.size() * sizeof(wchar_t));
        name.MaximumLength = static_cast<USHORT>(name.Length + sizeof(wchar_t));
        name.Buffer = path.data();
        OBJECT_ATTRIBUTES attributes{};
        InitializeObjectAttributes(&attributes, &name, OBJ_CASE_INSENSITIVE, nullptr, nullptr);
        return call(&handle, access, &attributes);
    }

    static OpenDirectory api() {
        const auto nt = GetModuleHandleW(L"ntdll.dll");
        const auto proc = nt ? GetProcAddress(nt, "NtOpenDirectoryObject") : nullptr;
        if (!proc) { SetLastError(ERROR_PROC_NOT_FOUND); return nullptr; }
        static_assert(sizeof(proc) == sizeof(OpenDirectory));
        OpenDirectory call = nullptr;
        std::memcpy(&call, &proc, sizeof(call));
        return call;
    }

    static bool verify_token(HANDLE token, DWORD session, PSID account) {
        DWORD assigned = 0, size = 0;
        if (!GetTokenInformation(token, TokenSessionId, &assigned, sizeof(assigned), &size)) return false;
        if (assigned != session || IsTokenRestricted(token)) { SetLastError(ERROR_ACCESS_DENIED); return false; }
        TOKEN_ELEVATION elevation{};
        if (!GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &size)) return false;
        if (elevation.TokenIsElevated) { SetLastError(ERROR_ACCESS_DENIED); return false; }
        GetTokenInformation(token, TokenIntegrityLevel, nullptr, 0, &size);
        std::vector<BYTE> level(size && size <= 4096 ? size : 0);
        if (level.empty() || !GetTokenInformation(token, TokenIntegrityLevel, level.data(), size, &size)) return false;
        if (!IsWellKnownSid(reinterpret_cast<TOKEN_MANDATORY_LABEL*>(level.data())->Label.Sid, WinMediumLabelSid)) {
            SetLastError(ERROR_ACCESS_DENIED);
            return false;
        }
        GetTokenInformation(token, TokenUser, nullptr, 0, &size);
        std::vector<BYTE> identity(size && size <= 4096 ? size : 0);
        if (identity.empty() || !GetTokenInformation(token, TokenUser, identity.data(), size, &size)) return false;
        if (!EqualSid(account, reinterpret_cast<TOKEN_USER*>(identity.data())->User.Sid)) {
            SetLastError(ERROR_INVALID_SID);
            return false;
        }
        return true;
    }

    bool preparation_failed(const char* phase) const {
        const auto error = GetLastError();
        std::fprintf(stderr, "Session %s preparation: %s failed (Windows error %lu)\n",
                     label(), phase, static_cast<unsigned long>(error));
        SetLastError(error);
        return false;
    }

    bool supported_access(OpenDirectory call, DWORD session, HANDLE thread_token,
                          ACCESS_MASK access, NTSTATUS& status) const {
        if (!ImpersonateLoggedOnUser(thread_token)) return false;
        LocalHandle check;
        status = open(call, session, access, check.value, leaf());
        if (!RevertToSelf()) {
            TerminateProcess(GetCurrentProcess(), 2);
            return false;
        }
        return true;
    }

    bool save_dacl(OpenDirectory call, DWORD session, PACL& old, BOOL& defaulted) {
        const auto opened = open(call, session, READ_CONTROL | WRITE_DAC, directory.value, leaf());
        if (opened < 0) {
            std::fprintf(stderr, "Opening this runner's session %s DACL for administration: 0x%08lx\n",
                         label(), static_cast<unsigned long>(static_cast<DWORD>(opened)));
            SetLastError(ERROR_ACCESS_DENIED);
            return false;
        }
        if (!read_dacl(original)) return false;
        BOOL has_dacl = FALSE;
        if (!GetSecurityDescriptorDacl(original.data(), &has_dacl, &old, &defaulted)) return false;
        if (!has_dacl || !old) { SetLastError(ERROR_INVALID_ACL); return false; }
        return true;
    }

    bool apply_dacl(PACL next, BOOL defaulted) {
        SECURITY_DESCRIPTOR descriptor{};
        changed = InitializeSecurityDescriptor(&descriptor, SECURITY_DESCRIPTOR_REVISION) &&
            SetSecurityDescriptorDacl(&descriptor, TRUE, next, defaulted) &&
            SetKernelObjectSecurity(directory.value, DACL_SECURITY_INFORMATION, &descriptor);
        return changed;
    }

    static PSID verified_logon_sid(HANDLE token, std::vector<BYTE>& info) {
        if (!token_part(token, TokenLogonSid, info) || info.size() < sizeof(TOKEN_GROUPS)) return nullptr;
        const auto* groups = reinterpret_cast<const TOKEN_GROUPS*>(info.data());
        constexpr DWORD active = SE_GROUP_LOGON_ID | SE_GROUP_ENABLED;
        constexpr SID_IDENTIFIER_AUTHORITY nt = SECURITY_NT_AUTHORITY;
        if (groups->GroupCount != 1 || (groups->Groups[0].Attributes & active) != active ||
            (groups->Groups[0].Attributes & SE_GROUP_USE_FOR_DENY_ONLY)) return nullptr;
        const auto sid = groups->Groups[0].Sid;
        if (!IsValidSid(sid) || *GetSidSubAuthorityCount(sid) != SECURITY_LOGON_IDS_RID_COUNT ||
            std::memcmp(GetSidIdentifierAuthority(sid), &nt, sizeof(nt)) != 0 ||
            *GetSidSubAuthority(sid, 0) != SECURITY_LOGON_IDS_RID) return nullptr;
        return sid;
    }

    struct InteractiveShell {
        HWND window = nullptr;
        DWORD pid = 0;
        LocalHandle process, token;
        std::vector<BYTE> logon_info;

        bool stable() const {
            DWORD current_pid = 0;
            return window && process.value && GetShellWindow() == window &&
                GetWindowThreadProcessId(window, &current_pid) && current_pid == pid &&
                GetProcessId(process.value) == pid && WaitForSingleObject(process.value, 0) == WAIT_TIMEOUT;
        }
    };

    static PSID verified_shell_logon(InteractiveShell& shell, DWORD session, HANDLE host,
                                     PSID host_logon, PSID child_logon) {
        wchar_t desktop[32]{};
        DWORD size = 0;
        const bool default_desktop =
            GetUserObjectInformationW(GetThreadDesktop(GetCurrentThreadId()), UOI_NAME, desktop, sizeof(desktop), &size) &&
            CompareStringOrdinal(desktop, -1, L"Default", -1, TRUE) == CSTR_EQUAL;
        shell.window = default_desktop ? GetShellWindow() : nullptr;
        if (shell.window && GetWindowThreadProcessId(shell.window, &shell.pid) && shell.pid)
            shell.process.value = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, shell.pid);
        const bool stable = shell.stable();
        DWORD process_session = 0, token_session = 0;
        const bool process_same_session = stable && ProcessIdToSessionId(shell.pid, &process_session) &&
            process_session == session;
        wchar_t windows[MAX_PATH]{}, image[MAX_PATH]{};
        const auto directory_len = GetSystemWindowsDirectoryW(windows, MAX_PATH);
        bool exact_image = false;
        if (process_same_session && directory_len && directory_len < MAX_PATH) {
            std::wstring expected(windows, directory_len);
            if (expected.back() != L'\\') expected += L'\\';
            expected += L"explorer.exe";
            DWORD image_len = MAX_PATH;
            exact_image = QueryFullProcessImageNameW(shell.process.value, 0, image, &image_len) &&
                CompareStringOrdinal(image, static_cast<int>(image_len), expected.c_str(),
                                     static_cast<int>(expected.size()), TRUE) == CSTR_EQUAL;
        }
        const bool token_same_session = exact_image && OpenProcessToken(shell.process.value, TOKEN_QUERY, &shell.token.value) &&
            GetTokenInformation(shell.token.value, TokenSessionId, &token_session, sizeof(token_session), &size) &&
            token_session == session;
        std::vector<BYTE> shell_user, host_user;
        bool same_user = false;
        if (token_same_session && token_part(shell.token.value, TokenUser, shell_user) &&
            token_part(host, TokenUser, host_user) && shell_user.size() >= sizeof(TOKEN_USER) &&
            host_user.size() >= sizeof(TOKEN_USER)) {
            const auto a = reinterpret_cast<const TOKEN_USER*>(shell_user.data())->User.Sid;
            const auto b = reinterpret_cast<const TOKEN_USER*>(host_user.data())->User.Sid;
            same_user = IsValidSid(a) && IsValidSid(b) && EqualSid(a, b);
        }
        const auto logon = same_user ? verified_logon_sid(shell.token.value, shell.logon_info) : nullptr;
        const bool different_child = logon && !EqualSid(logon, child_logon);
        const bool stable_after = different_child && shell.stable();
        std::fprintf(stderr, "Interactive shell witness: default_desktop=%d stable=%d windows_explorer=%d session=%d "
            "token_session=%d same_user=%d active_logon=%d same_runner_logon=%d distinct_child_logon=%d rechecked=%d.\n",
            default_desktop, stable, exact_image, process_same_session, token_same_session, same_user,
            logon != nullptr, logon && EqualSid(logon, host_logon), different_child, stable_after);
        return stable_after ? logon : nullptr;
    }

    bool copy_logon_dacl(OpenDirectory call, DWORD session, HANDLE actual_child) {
        LocalHandle host;
        TOKEN_ELEVATION elevation{};
        DWORD host_session = 0, size = 0;
        if (kind != Kind::base ||
            !OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &host.value) ||
            !GetTokenInformation(host.value, TokenSessionId, &host_session, sizeof(host_session), &size) ||
            host_session != session ||
            !GetTokenInformation(host.value, TokenElevation, &elevation, sizeof(elevation), &size) ||
            !elevation.TokenIsElevated) {
            SetLastError(ERROR_ACCESS_DENIED);
            return preparation_failed("verify the elevated interactive runner");
        }
        std::vector<BYTE> child_info, host_info;
        const auto child_logon = verified_logon_sid(actual_child, child_info);
        const auto host_logon = verified_logon_sid(host.value, host_info);
        if (!child_logon || !host_logon || EqualSid(child_logon, host_logon)) {
            SetLastError(ERROR_INVALID_SID);
            return preparation_failed("verify distinct enabled logon SIDs for the runner and real child");
        }
        PACL old = nullptr;
        BOOL defaulted = FALSE;
        if (!save_dacl(call, session, old, defaulted)) return preparation_failed("save the original DACL");
        if (!IsValidAcl(old)) return preparation_failed("validate the original DACL");
        struct DirectAllow { PSID sid; WORD bytes; };
        std::vector<DirectAllow> candidates;
        // Refuse unfamiliar ACE structures so an existing entry for the
        // child cannot accidentally be missed. Never copy an inherited ACE.
        for (DWORD index = 0; index < old->AceCount; ++index) {
            LPVOID raw = nullptr;
            if (!GetAce(old, index, &raw)) return preparation_failed("inspect the existing DACL");
            const auto* ace = static_cast<const ACCESS_ALLOWED_ACE*>(raw);
            if ((ace->Header.AceType != ACCESS_ALLOWED_ACE_TYPE && ace->Header.AceType != ACCESS_DENIED_ACE_TYPE) ||
                ace->Header.AceSize < offsetof(ACCESS_ALLOWED_ACE, SidStart) + 8) {
                SetLastError(ERROR_INVALID_ACL);
                return preparation_failed("verify the DACL uses understood ACE types");
            }
            auto sid = const_cast<DWORD*>(&ace->SidStart);
            if (!IsValidSid(sid) || GetLengthSid(sid) > ace->Header.AceSize - offsetof(ACCESS_ALLOWED_ACE, SidStart) ||
                EqualSid(sid, child_logon)) {
                SetLastError(ERROR_INVALID_ACL);
                return preparation_failed("verify no existing ACE for the child's logon");
            }
            if (ace->Header.AceType == ACCESS_ALLOWED_ACE_TYPE && ace->Header.AceFlags == 0 &&
                ace->Mask == normal_logon_rights)
                candidates.push_back({sid, ace->Header.AceSize});
        }
        const auto witnessed = [&](PSID sid) -> WORD {
            if (sid) for (const auto& candidate : candidates)
                if (EqualSid(sid, candidate.sid)) return candidate.bytes;
            return 0;
        };
        InteractiveShell shell;
        WORD witnessed_bytes = witnessed(host_logon);
        const bool shell_fallback = !witnessed_bytes;
        if (shell_fallback)
            witnessed_bytes = witnessed(verified_shell_logon(shell, session, host.value, host_logon, child_logon));
        std::fprintf(stderr, "BaseNamedObjects exact direct 0xF000F witness: runner_logon=%d interactive_shell_logon=%d.\n",
                     !shell_fallback, shell_fallback && witnessed_bytes != 0);
        const auto bytes = static_cast<DWORD>(old->AclSize) + witnessed_bytes;
        if (!witnessed_bytes || bytes > UINT16_MAX) {
            SetLastError(ERROR_INVALID_ACL);
            return preparation_failed("find an exact direct 0xF000F allow for a verified logon");
        }
        // Append one ACE to a copy. The other entries and their order are
        // unchanged. No new right is granted to the user SID or other logons.
        std::vector<BYTE> replacement(bytes);
        std::memcpy(replacement.data(), old, old->AclSize);
        const auto next = reinterpret_cast<PACL>(replacement.data());
        next->AclSize = static_cast<WORD>(bytes);
        if (!AddAccessAllowedAceEx(next, old->AclRevision, 0, normal_logon_rights, child_logon))
            return preparation_failed("prepare the witnessed direct ACE for the child's logon only");
        if (shell_fallback && !shell.stable()) {
            SetLastError(ERROR_INVALID_HANDLE);
            return preparation_failed("recheck the interactive shell before applying the DACL");
        }
        if (!apply_dacl(next, defaulted))
            return preparation_failed("copy the witnessed direct ACE to the child's logon only");
        std::fprintf(stderr, "Hosted Edge BaseNamedObjects: copied direct %s-logon allow 0x%lx to the verified child logon; no user grant.\n",
                     shell_fallback ? "interactive-shell" : "runner", static_cast<unsigned long>(normal_logon_rights));
        return true;
    }

    bool start(DWORD pid, HANDLE process, HANDLE logon_token, PSID account, ACCESS_MASK access,
               bool lowbox_broker = false) {
        if (!hosted_recipe()) { SetLastError(ERROR_ACCESS_DENIED); return false; }
        if ((kind == Kind::app_container && (access != with_subdirectory || lowbox_broker)) ||
            (access != recipe_access && access != with_subdirectory)) {
            SetLastError(ERROR_INVALID_PARAMETER);
            return false;
        }
        DWORD parent_session = 0, session = 0;
        if (!ProcessIdToSessionId(GetCurrentProcessId(), &parent_session) || !ProcessIdToSessionId(pid, &session))
            return false;
        if (!session || session != parent_session) { SetLastError(ERROR_ACCESS_DENIED); return false; }

        // The suspended child owns the actual logon SID. LogonUser creates
        // a different logon, suitable only for the account-based paths.
        LocalHandle token, identity;
        if (!OpenProcessToken(process, TOKEN_QUERY, &token.value))
            return preparation_failed("query the suspended child's token");
        if (!verify_token(token.value, session, account))
            return preparation_failed("verify the suspended child's account and session");
        const auto call = api();
        if (!call) return preparation_failed("resolve NtOpenDirectoryObject");
        if (lowbox_broker) return copy_logon_dacl(call, session, token.value);
        DWORD logon_session = 0, session_bytes = 0;
        if (!GetTokenInformation(logon_token, TokenSessionId, &logon_session, sizeof(logon_session), &session_bytes))
            return preparation_failed("query the local logon token's session");
        std::fprintf(stderr, "Recipe namespace access check: local logon token session=%lu; target session=%lu.\n",
                     static_cast<unsigned long>(logon_session), static_cast<unsigned long>(session));
        if (!verify_token(logon_token, session, account))
            return preparation_failed("verify the local logon token's account and session");
        if (!DuplicateTokenEx(logon_token, TOKEN_QUERY | TOKEN_IMPERSONATE, nullptr, SecurityImpersonation,
                              TokenImpersonation, &identity.value))
            return preparation_failed("prepare the verified local account's access check");
        NTSTATUS before = 0;
        if (!supported_access(call, session, identity.value, access, before))
            return preparation_failed("check session directory access as the local account");
        std::fprintf(stderr, "Recipe account session %s before grant: mask=0x%lx result=0x%08lx\n",
                     label(), static_cast<unsigned long>(access), static_cast<unsigned long>(static_cast<DWORD>(before)));
        if (before >= 0) return true;
        if (before != denied) { SetLastError(ERROR_INVALID_HANDLE); return false; }

        BOOL defaulted = FALSE;
        PACL old = nullptr, updated = nullptr;
        if (!save_dacl(call, session, old, defaulted)) return false;
        EXPLICIT_ACCESSW allow{};
        allow.grfAccessPermissions = access;
        allow.grfAccessMode = GRANT_ACCESS;
        allow.grfInheritance = NO_INHERITANCE;
        BuildTrusteeWithSidW(&allow.Trustee, account);
        const auto result = SetEntriesInAclW(1, &allow, old, &updated);
        if (result != ERROR_SUCCESS) { SetLastError(result); return false; }
        apply_dacl(updated, defaulted);
        const auto update_error = changed ? ERROR_SUCCESS : GetLastError();
        LocalFree(updated);
        if (!changed) { SetLastError(update_error); return false; }

        NTSTATUS after = 0;
        if (!supported_access(call, session, identity.value, access, after))
            return preparation_failed("recheck session directory access as the local account");
        std::fprintf(stderr, "Recipe account session %s after grant: mask=0x%lx result=0x%08lx\n",
                     label(), static_cast<unsigned long>(access), static_cast<unsigned long>(static_cast<DWORD>(after)));
        if (after < 0) { SetLastError(ERROR_ACCESS_DENIED); return false; }
        return true;
    }
};

NamespaceObservation observe_namespace(DWORD session, bool check_logon) {
    NamespaceObservation result;
    const auto open = RecipeNamespace::api();
    if (open && session && session != UINT32_MAX) {
        result.have_directory_api = true;
        const auto check = [&](ACCESS_MASK access) {
            LocalHandle directory;
            return RecipeNamespace::open(open, session, access, directory.value);
        };
        result.minimum = check(RecipeNamespace::recipe_access);
        result.with_subdirectory = check(RecipeNamespace::with_subdirectory);
        const auto lowbox_read = check(RecipeNamespace::lowbox_read);
        std::printf("Actual child directory: mask_0x7=0x%08lx mask_0xf=0x%08lx mask_0x20003=0x%08lx\n",
                    static_cast<unsigned long>(static_cast<DWORD>(result.minimum)),
                    static_cast<unsigned long>(static_cast<DWORD>(result.with_subdirectory)),
                    static_cast<unsigned long>(static_cast<DWORD>(lowbox_read)));
        if (check_logon) {
            const auto logon = check(RecipeNamespace::normal_logon_rights);
            result.normal_logon_access = logon >= 0;
            std::printf("Actual disposable logon: BaseNamedObjects mask=0x%08lx ntstatus=0x%08lx\n",
                        static_cast<unsigned long>(RecipeNamespace::normal_logon_rights),
                        static_cast<unsigned long>(static_cast<DWORD>(logon)));
        }
    }
    // Fresh unrelated names, no ownership or waiting. Close each handle before
    // doing anything else, so the recipe never touches an existing browser object.
    const auto make = [](const wchar_t* prefix) -> DWORD {
        GUID id{};
        wchar_t id_text[40]{};
        if (FAILED(CoCreateGuid(&id)) || !StringFromGUID2(id, id_text, 40)) return ERROR_GEN_FAILURE;
        const auto name = std::wstring(prefix) + L"NoteViveRecipeMutex-" + id_text;
        SetLastError(ERROR_SUCCESS);
        LocalHandle handle{CreateMutexW(nullptr, FALSE, name.c_str())};
        const auto error = GetLastError();
        if (handle.value && error != ERROR_ALREADY_EXISTS) return ERROR_SUCCESS;
        return error ? error : ERROR_GEN_FAILURE;
    };
    result.bare_mutex = make(L"");
    result.local_mutex = make(L"Local\\");
    std::printf("Actual child mutex: implicit_session=%lu Local=%lu\n",
                static_cast<unsigned long>(result.bare_mutex), static_cast<unsigned long>(result.local_mutex));
    return result;
}

void observe_renderer_objects(DWORD session) {
    // Diagnostics only: no rights are added.
    // This synthetic restricting SID is not a copy of Edge's renderer token.
    if (const auto call = RecipeNamespace::api(); call && session && session != UINT32_MAX) {
        for (const ACCESS_MASK access : {0x3u, 0x7u, 0xfu}) {
            LocalHandle directory;
            const auto status = RecipeNamespace::open(call, session, access, directory.value, L"AppContainerNamedObjects");
            std::printf("AppContainerNamedObjects requested=0x%lx ntstatus=0x%08lx\n",
                        static_cast<unsigned long>(access), static_cast<unsigned long>(static_cast<DWORD>(status)));
        }
    }
    wchar_t desktop_name[256]{};
    DWORD length = 0;
    LocalHandle token, restricted;
    alignas(DWORD) BYTE sid[SECURITY_MAX_SID_SIZE]{};
    DWORD size = sizeof(sid);
    SID_AND_ATTRIBUTES restriction{sid, 0};
    const auto desk = GetThreadDesktop(GetCurrentThreadId());
    if (!desk || !GetUserObjectInformationW(desk, UOI_NAME, desktop_name, sizeof(desktop_name), &length) ||
        !CreateWellKnownSid(WinRestrictedCodeSid, nullptr, sid, &size) ||
        !OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_DUPLICATE, &token.value) ||
        !CreateRestrictedToken(token.value, 0, 0, nullptr, 0, nullptr, 1, &restriction, &restricted.value)) {
        std::printf("Renderer desktop read-only observation unavailable: win32=%lu\n",
                    static_cast<unsigned long>(GetLastError()));
        return;
    }
    const auto observe = [&] {
        const auto station = OpenWindowStationW(L"WinSta0", FALSE, WINSTA_READATTRIBUTES);
        const DWORD station_error = station ? ERROR_SUCCESS : GetLastError();
        if (station) CloseWindowStation(station);
        const auto input = OpenDesktopW(desktop_name, 0, FALSE, DESKTOP_READOBJECTS);
        const DWORD desktop_error = input ? ERROR_SUCCESS : GetLastError();
        if (input) CloseDesktop(input);
        return std::pair<DWORD, DWORD>{station_error, desktop_error};
    };
    const auto normal = observe();
    if (!ImpersonateLoggedOnUser(restricted.value)) {
        std::printf("Synthetic restricted desktop probe unavailable: win32=%lu\n",
                    static_cast<unsigned long>(GetLastError()));
        return;
    }
    const auto limited = observe();
    if (!RevertToSelf()) std::terminate();
    std::printf("Desktop query (synthetic restricting SID): normal station=%lu desktop=%lu; restricted station=%lu desktop=%lu\n",
                static_cast<unsigned long>(normal.first), static_cast<unsigned long>(normal.second),
                static_cast<unsigned long>(limited.first), static_cast<unsigned long>(limited.second));
}

void observe_appcontainer_links(DWORD session) {
    // Known names only, for this token and its session. Do not enumerate a
    // namespace or send an object name/logon SID to the CI logs.
    if (!session || session == UINT32_MAX) return;
    const auto directory_api = RecipeNamespace::api();
    const auto ntdll = GetModuleHandleW(L"ntdll.dll");
    const auto open_proc = ntdll ? GetProcAddress(ntdll, "NtOpenSymbolicLinkObject") : nullptr;
    const auto query_proc = ntdll ? GetProcAddress(ntdll, "NtQuerySymbolicLinkObject") : nullptr;
    if (!directory_api || !open_proc || !query_proc) return;
    using QueryLink = NTSTATUS (NTAPI*)(HANDLE, PUNICODE_STRING, PULONG);
    RecipeNamespace::OpenDirectory open_link = nullptr; // Same signature as NtOpenDirectoryObject.
    QueryLink query_link = nullptr;
    static_assert(sizeof(open_proc) == sizeof(open_link) && sizeof(query_proc) == sizeof(query_link));
    std::memcpy(&open_link, &open_proc, sizeof(open_link));
    std::memcpy(&query_link, &query_proc, sizeof(query_link));
    std::wstring logon_sid;
    LocalHandle self;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &self.value)) {
        DWORD length = 0;
        GetTokenInformation(self.value, TokenLogonSid, nullptr, 0, &length);
        std::vector<BYTE> bytes(length && length <= 4096 ? length : 0);
        if (bytes.size() >= sizeof(TOKEN_GROUPS) &&
            GetTokenInformation(self.value, TokenLogonSid, bytes.data(), length, &length)) {
            const auto* groups = reinterpret_cast<const TOKEN_GROUPS*>(bytes.data());
            LPWSTR local_sid = nullptr;
            if (groups->GroupCount == 1 && (groups->Groups[0].Attributes & SE_GROUP_LOGON_ID) == SE_GROUP_LOGON_ID &&
                ConvertSidToStringSidW(groups->Groups[0].Sid, &local_sid)) {
                logon_sid = local_sid;
                LocalFree(local_sid);
            }
        }
    }
    const std::wstring session_root = L"\\Sessions\\" + std::to_wstring(session) + L"\\";
    const auto app_root = session_root + L"AppContainerNamedObjects";
    const auto read = [&](const char* role, const std::wstring& leaf) {
        LocalHandle link, query_handle, create_handle;
        const auto opened = RecipeNamespace::open(open_link, session, 0x1, link.value, leaf.c_str());
        const auto visible = RecipeNamespace::open(directory_api, session, 0x3, query_handle.value, leaf.c_str());
        const auto create = RecipeNamespace::open(directory_api, session, 0xf, create_handle.value, leaf.c_str());
        const char* link_form = "unavailable";
        NTSTATUS queried = opened;
        if (opened >= 0) {
            wchar_t text[512]{};
            UNICODE_STRING target{0, static_cast<USHORT>(sizeof(text)), text};
            queried = query_link(link.value, &target, nullptr);
            if (queried >= 0 && target.Length && target.Length <= sizeof(text) && target.Length % sizeof(wchar_t) == 0) {
                const std::wstring result(target.Buffer, target.Length / sizeof(wchar_t));
                const bool actual_logon = !logon_sid.empty() && result.find(logon_sid) != std::wstring::npos;
                const auto same = [&](const std::wstring& value) {
                    return CompareStringOrdinal(result.c_str(), -1, value.c_str(), -1, TRUE) == CSTR_EQUAL;
                };
                link_form = actual_logon ? "contains-own-logon-sid" : same(app_root) ? "session-app-root" :
                    same(L"\\AppContainerNamedObjects") ? "global-app-root" : "other";
            }
        }
        std::printf("AppContainer object route %s: link_open=0x%08lx link_query=0x%08lx target=%s "
            "directory_read=0x%08lx directory_create_access=0x%08lx\n", role,
            static_cast<unsigned long>(static_cast<DWORD>(opened)), static_cast<unsigned long>(static_cast<DWORD>(queried)),
            link_form, static_cast<unsigned long>(static_cast<DWORD>(visible)),
            static_cast<unsigned long>(static_cast<DWORD>(create)));
    };
    read("base-alias", L"BaseNamedObjects\\AppContainerNamedObjects");
    read("base-restricted-alias", L"BaseNamedObjects\\Restricted\\AppContainerNamedObjects");
    if (!logon_sid.empty()) {
        read("own-logon-base", L"BaseNamedObjects\\" + logon_sid);
        read("own-logon-base-alias", L"BaseNamedObjects\\" + logon_sid + L"\\AppContainerNamedObjects");
        read("own-logon-under-app", L"AppContainerNamedObjects\\" + logon_sid);
    }
}

bool observe_lowbox_creation(DWORD session) {
    // Use Chromium's kernelbase entry point, but no Edge package identifier,
    // capability, registration, impersonation or child is created here.
    if (!disposable_recipe_account()) return false;
    using CreateLowbox = BOOL (WINAPI*)(HANDLE, PSECURITY_CAPABILITIES, PHANDLE);
    const auto module = GetModuleHandleW(L"kernelbase.dll");
    const auto call = module ? GetProcAddress(module, "CreateAppContainerToken") : nullptr;
    if (!call) {
        std::puts("Synthetic LowBox: kernelbase entry not available.");
        return false;
    }
    static_assert(sizeof(call) == sizeof(CreateLowbox));
    CreateLowbox create = nullptr;
    std::memcpy(&create, &call, sizeof(create));
    LocalHandle standard, restricted;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ALL_ACCESS, &standard.value)) {
        std::printf("Synthetic LowBox: open self token win32=%lu\n", static_cast<unsigned long>(GetLastError()));
        return false;
    }
    const auto has_logon_sid = [](HANDLE token) {
        DWORD size = 0;
        GetTokenInformation(token, TokenLogonSid, nullptr, 0, &size);
        std::vector<BYTE> groups(size && size <= 4096 ? size : 0);
        if (groups.size() < sizeof(TOKEN_GROUPS) ||
            !GetTokenInformation(token, TokenLogonSid, groups.data(), size, &size)) return false;
        const auto* info = reinterpret_cast<const TOKEN_GROUPS*>(groups.data());
        return info->GroupCount == 1 && IsValidSid(info->Groups[0].Sid) &&
            (info->Groups[0].Attributes & SE_GROUP_LOGON_ID) == SE_GROUP_LOGON_ID;
    };
    const auto probe = [&](const char* arm, HANDLE base) -> bool {
        GUID id{};
        wchar_t guid[40]{};
        if (FAILED(CoCreateGuid(&id)) || StringFromGUID2(id, guid, 40) != 39) return false;
        const std::wstring moniker = L"NoteVive.Recipe." + std::wstring(guid + 1, 36);
        PSID package = nullptr;
        const HRESULT derive = DeriveAppContainerSidFromAppContainerName(moniker.c_str(), &package);
        if (FAILED(derive) || !package) {
            if (package) FreeSid(package);
            std::printf("Synthetic LowBox %s: derive=0x%08lx\n", arm,
                        static_cast<unsigned long>(static_cast<DWORD>(derive)));
            return false;
        }
        SECURITY_CAPABILITIES capabilities{};
        capabilities.AppContainerSid = package;
        LocalHandle lowbox, full_access_copy;
        SetLastError(ERROR_SUCCESS);
        const bool made = create(base, &capabilities, &lowbox.value) && lowbox.value;
        const DWORD create_error = made ? ERROR_SUCCESS : GetLastError();
        DWORD copy_error = UINT32_MAX, path_error = UINT32_MAX, in_app = 0, selected_session = UINT32_MAX;
        bool attached_package = false;
        if (made) {
            const auto self = GetCurrentProcess();
            copy_error = DuplicateHandle(self, lowbox.value, self, &full_access_copy.value, TOKEN_ALL_ACCESS, FALSE, 0) ?
                ERROR_SUCCESS : GetLastError();
            DWORD used = 0;
            GetTokenInformation(lowbox.value, TokenIsAppContainer, &in_app, sizeof(in_app), &used);
            GetTokenInformation(lowbox.value, TokenSessionId, &selected_session, sizeof(selected_session), &used);
            GetTokenInformation(lowbox.value, TokenAppContainerSid, nullptr, 0, &used);
            std::vector<BYTE> sid(used && used <= 4096 ? used : 0);
            if (sid.size() >= sizeof(TOKEN_APPCONTAINER_INFORMATION) &&
                GetTokenInformation(lowbox.value, TokenAppContainerSid, sid.data(), used, &used)) {
                const auto actual = reinterpret_cast<const TOKEN_APPCONTAINER_INFORMATION*>(sid.data())->TokenAppContainer;
                attached_package = actual && IsValidSid(actual) && EqualSid(actual, package);
            }
        }
        wchar_t path[512]{};
        ULONG path_size = 0;
        const char* path_form = "unavailable";
        const auto starts_with = [&](const std::wstring& prefix) {
            return CompareStringOrdinal(path, static_cast<int>(prefix.size()), prefix.c_str(),
                                        static_cast<int>(prefix.size()), TRUE) == CSTR_EQUAL;
        };
        if (GetAppContainerNamedObjectPath(made ? lowbox.value : nullptr, made ? nullptr : package,
                                          512, path, &path_size)) {
            path_error = ERROR_SUCCESS;
            const auto expected = L"\\Sessions\\" + std::to_wstring(session) + L"\\AppContainerNamedObjects\\";
            path_form = starts_with(expected) ? "nt-session" :
                starts_with(L"\\AppContainerNamedObjects\\") ? "root-appcontainer" :
                starts_with(L"AppContainerNamedObjects\\") ? "relative-appcontainer" : "other";
        } else path_error = GetLastError();
        FreeSid(package);
        std::printf("Synthetic LowBox %s: logon_sid=%d create_ok=%d create_win32=%lu duplicate_all_win32=%lu "
            "appcontainer=%lu package_match=%d token_session_match=%d path_win32=%lu path_form=%s\n",
            arm, has_logon_sid(base), made, static_cast<unsigned long>(create_error),
            static_cast<unsigned long>(copy_error), static_cast<unsigned long>(in_app), attached_package,
            selected_session == session, static_cast<unsigned long>(path_error), path_form);
        // The Win32 path API may return a relative name. The actual token
        // session, not the format of its path string, is the identity check.
        return made && copy_error == ERROR_SUCCESS && in_app == 1 &&
            attached_package && selected_session == session;
    };
    const bool standard_passed = probe("standard", standard.value);
    alignas(DWORD) BYTE null_sid[SECURITY_MAX_SID_SIZE]{}, low_label[SECURITY_MAX_SID_SIZE]{};
    DWORD null_size = sizeof(null_sid), low_size = sizeof(low_label);
    SID_AND_ATTRIBUTES limit{null_sid, 0};
    TOKEN_MANDATORY_LABEL label{{low_label, SE_GROUP_INTEGRITY}};
    if (!CreateWellKnownSid(WinNullSid, nullptr, null_sid, &null_size) ||
        !CreateWellKnownSid(WinLowLabelSid, nullptr, low_label, &low_size) ||
        !CreateRestrictedToken(standard.value, DISABLE_MAX_PRIVILEGE, 0, nullptr, 0, nullptr, 1,
                               &limit, &restricted.value) ||
        !SetTokenInformation(restricted.value, TokenIntegrityLevel, &label,
                             static_cast<DWORD>(sizeof(label) + low_size))) {
        std::printf("Synthetic LowBox restricted-low preparation: win32=%lu\n",
                    static_cast<unsigned long>(GetLastError()));
        return false;
    }
    const bool restricted_passed = probe("restricted-low", restricted.value);
    return standard_passed && restricted_passed;
}

int edge_namespace_control() {
    if (!_wfreopen(L"out\\edge-namespace-control.log", L"wb", stdout)) return 3;
    require(ordinary_token(), "Edge namespace control is not a standard account");
    const auto session = report_session("edge_namespace_control", GetCurrentProcessId(), GetCurrentProcess());
    observe_renderer_objects(session);
    const bool lowbox_before = observe_lowbox_creation(session);
    std::printf("Edge preflight control (without AppContainer ACL): synthetic_lowbox=%d\n", lowbox_before);
    BOOL in_job = FALSE;
    require(IsProcessInJob(GetCurrentProcess(), nullptr, &in_job) && in_job, "missing outer recipe job in control");
    const DWORD plain = launch_in_test_job(false), ui_limited = launch_in_test_job(true);
    std::printf("Edge job control: inherited=1 plain=%lu ui_limited=%lu\n",
                static_cast<unsigned long>(plain), static_cast<unsigned long>(ui_limited));
    if (plain == ERROR_SUCCESS && ui_limited != ERROR_SUCCESS)
        std::puts("Edge job control: remove recipe container.");
    const auto result = observe_namespace(session);
    if (result.local_mutex == ERROR_SUCCESS) {
        std::puts("Edge namespace control: use 0x7.");
        return 0;
    }
    if (result.have_directory_api && result.minimum >= 0 &&
        result.with_subdirectory == RecipeNamespace::denied &&
        result.bare_mutex == ERROR_ACCESS_DENIED && result.local_mutex == ERROR_ACCESS_DENIED) {
        std::puts("Edge namespace control: test 0x8 addition.");
        return 0;
    }
    std::puts("Edge namespace control: measurements do not support any permission extension.");
    return 1;
}

struct RecipeDesktop {
    static constexpr DWORD station_access = STANDARD_RIGHTS_REQUIRED | WINSTA_ALL_ACCESS;
    static constexpr DWORD desktop_access = STANDARD_RIGHTS_REQUIRED | DESKTOP_READOBJECTS |
        DESKTOP_WRITEOBJECTS | DESKTOP_CREATEWINDOW | DESKTOP_CREATEMENU | DESKTOP_ENUMERATE |
        DESKTOP_HOOKCONTROL | DESKTOP_JOURNALRECORD | DESKTOP_JOURNALPLAYBACK | DESKTOP_SWITCHDESKTOP;
    HDESK original = nullptr, temporary = nullptr;
    HWINSTA station = nullptr;
    std::vector<BYTE> station_descriptor;
    bool station_changed = false, switched = false;
    std::wstring path;

    ~RecipeDesktop() {
        if (!restore()) std::fputs("Unable to restore recipe desktop or station ACL.\n", stderr);
        if (temporary) CloseDesktop(temporary);
        if (original) CloseDesktop(original);
        if (station) CloseWindowStation(station);
    }
    bool restore() {
        if (switched && SwitchDesktop(original)) switched = false;
        if (station_changed) {
            SECURITY_INFORMATION security = DACL_SECURITY_INFORMATION;
            if (SetUserObjectSecurity(station, &security, station_descriptor.data())) station_changed = false;
        }
        return !switched && !station_changed;
    }
    static std::pair<DWORD, DWORD> log_label(HANDLE object, const char* name) {
        SECURITY_INFORMATION security = LABEL_SECURITY_INFORMATION;
        DWORD needed = 0;
        GetUserObjectSecurity(object, &security, nullptr, 0, &needed);
        std::vector<BYTE> descriptor(needed && needed <= 65536 ? needed : 0);
        if (descriptor.empty() ||
            !GetUserObjectSecurity(object, &security, descriptor.data(), needed, &needed)) {
            std::fprintf(stderr, "%s integrity label unreadable (%lu)\n", name,
                         static_cast<unsigned long>(GetLastError()));
            return {UINT32_MAX, 0};
        }
        BOOL present = FALSE, defaulted = FALSE;
        PACL sacl = nullptr;
        if (GetSecurityDescriptorSacl(descriptor.data(), &present, &sacl, &defaulted) && present && sacl) {
            for (DWORD i = 0; i < sacl->AceCount; ++i) {
                void* ace = nullptr;
                if (!GetAce(sacl, i, &ace) ||
                    static_cast<ACE_HEADER*>(ace)->AceType != SYSTEM_MANDATORY_LABEL_ACE_TYPE) continue;
                auto* label = static_cast<SYSTEM_MANDATORY_LABEL_ACE*>(ace);
                PSID sid = &label->SidStart;
                if (IsValidSid(sid) && *GetSidSubAuthorityCount(sid)) {
                    const DWORD level = *GetSidSubAuthority(sid, *GetSidSubAuthorityCount(sid) - 1);
                    std::fprintf(stderr, "%s integrity=0x%04lx mandatory_policy=0x%lx\n", name,
                        static_cast<unsigned long>(level),
                        static_cast<unsigned long>(label->Mask));
                    return {level, label->Mask};
                }
            }
        }
        std::fprintf(stderr, "%s has no explicit integrity label\n", name);
        return {UINT32_MAX, 0};
    }
    static bool sandbox_desktop_aces(HDESK source, std::wstring& additions) {
        SECURITY_INFORMATION request = DACL_SECURITY_INFORMATION;
        DWORD length = 0;
        GetUserObjectSecurity(source, &request, nullptr, 0, &length);
        std::vector<BYTE> bytes(length && length <= 65536 ? length : 0);
        if (bytes.empty() || !GetUserObjectSecurity(source, &request, bytes.data(), length, &length)) return false;
        BOOL present = FALSE, defaulted = FALSE;
        PACL dacl = nullptr;
        if (!GetSecurityDescriptorDacl(bytes.data(), &present, &dacl, &defaulted) || !present || !dacl) {
            SetLastError(ERROR_INVALID_ACL);
            return false;
        }
        struct Entry { const wchar_t* sid; const char* label; DWORD allow = 0, deny = 0; };
        Entry entries[] = {{L"S-1-5-12", "RestrictedCode"},
                           {L"S-1-15-2-1", "AllApplicationPackages"},
                           {L"S-1-15-2-2", "AllRestrictedApplicationPackages"},
                           {nullptr, "LogonSid"}};
        GENERIC_MAPPING desktop_generic{
            READ_CONTROL | DESKTOP_READOBJECTS | DESKTOP_ENUMERATE,
            READ_CONTROL | DESKTOP_CREATEMENU | DESKTOP_CREATEWINDOW | DESKTOP_HOOKCONTROL |
                DESKTOP_JOURNALPLAYBACK | DESKTOP_JOURNALRECORD | DESKTOP_WRITEOBJECTS,
            READ_CONTROL | DESKTOP_SWITCHDESKTOP, desktop_access};
        for (DWORD n = 0; n < dacl->AceCount; ++n) {
            void* raw = nullptr;
            if (!GetAce(dacl, n, &raw)) return false;
            const auto* head = static_cast<const ACE_HEADER*>(raw);
            if (head->AceFlags & INHERIT_ONLY_ACE ||
                (head->AceType != ACCESS_ALLOWED_ACE_TYPE && head->AceType != ACCESS_DENIED_ACE_TYPE)) continue;
            auto* ace = static_cast<ACCESS_ALLOWED_ACE*>(raw); // simple allow/deny ACEs share this layout
            LPWSTR text = nullptr;
            if (!ConvertSidToStringSidW(&ace->SidStart, &text)) return false;
            DWORD mask = ace->Mask;
            MapGenericMask(&mask, &desktop_generic);
            for (auto& entry : entries) {
                const bool matches = entry.sid ? std::wcscmp(text, entry.sid) == 0 :
                    std::wcsncmp(text, L"S-1-5-5-", 8) == 0;
                if (matches) {
                    if (head->AceType == ACCESS_ALLOWED_ACE_TYPE) entry.allow |= mask;
                    else entry.deny |= mask;
                    break;
                }
            }
            LocalFree(text);
        }
        // The alternate desktop in Chromium uses the current desktop's DACL.
        // Keep only rights observed on Default; never copy logon identities or
        // ownership, hooks, journaling, creating windows/menus or switching it.
        constexpr DWORD inspect = READ_CONTROL | DESKTOP_READOBJECTS | DESKTOP_ENUMERATE | DESKTOP_WRITEOBJECTS;
        for (const auto& entry : entries) {
            const DWORD copy = entry.sid ? (entry.allow & ~entry.deny & inspect) : 0;
            std::fprintf(stderr, "Original Default ACE %s: allow=0x%lx deny=0x%lx recipe=0x%lx\n",
                        entry.label, static_cast<unsigned long>(entry.allow),
                        static_cast<unsigned long>(entry.deny), static_cast<unsigned long>(copy));
            if (copy) {
                wchar_t rights[16]{};
                if (std::swprintf(rights, 16, L"0x%lx", static_cast<unsigned long>(copy)) <= 0) return false;
                additions += L"(A;;";
                additions += rights;
                additions += L";;;";
                additions += entry.sid;
                additions += L")";
            }
        }
        return true;
    }
    static DWORD access_with(HANDLE thread_token, const wchar_t* station_name, const wchar_t* desktop_name = nullptr) {
        if (!ImpersonateLoggedOnUser(thread_token)) return GetLastError();
        HWINSTA station_check = OpenWindowStationW(station_name, FALSE, station_access);
        DWORD error = station_check ? ERROR_SUCCESS : GetLastError();
        if (station_check) CloseWindowStation(station_check);
        if (!error && desktop_name) {
            HDESK desktop_check = OpenDesktopW(desktop_name, 0, FALSE, desktop_access);
            error = desktop_check ? ERROR_SUCCESS : GetLastError();
            if (desktop_check) CloseDesktop(desktop_check);
        }
        if (!RevertToSelf()) {
            // Continuing this launcher under the wrong identity could make
            // restoration unreliable.
            TerminateProcess(GetCurrentProcess(), 2);
            return ERROR_ACCESS_DENIED;
        }
        return error;
    }
    bool start(HANDLE token, PSID account, bool edge_broker, bool grant_station = true) {
        if (!hosted_recipe()) {
            std::fputs("Run the recipe from an ordinary Windows account; desktop setup is limited to hosted CI.\n", stderr);
            SetLastError(ERROR_ACCESS_DENIED);
            return false;
        }
        wchar_t station_name[32]{};
        DWORD length = 0;
        if (!GetUserObjectInformationW(GetProcessWindowStation(), UOI_NAME, station_name, sizeof(station_name), &length))
            return false;
        if (CompareStringOrdinal(station_name, -1, L"WinSta0", -1, TRUE) != CSTR_EQUAL) {
            SetLastError(ERROR_INVALID_HANDLE);
            return false;
        }
        original = OpenInputDesktop(0, FALSE, DESKTOP_SWITCHDESKTOP | DESKTOP_READOBJECTS);
        if (!original) return false;
        wchar_t desktop_name[32]{};
        if (!GetUserObjectInformationW(original, UOI_NAME, desktop_name, sizeof(desktop_name), &length)) return false;
        if (CompareStringOrdinal(desktop_name, -1, L"Default", -1, TRUE) != CSTR_EQUAL) {
            // Never replace an active UAC, lock or other test desktop.
            SetLastError(ERROR_ACCESS_DENIED);
            return false;
        }
        std::wstring sandbox_aces;
        const auto default_security = OpenDesktopW(desktop_name, 0, FALSE,
            READ_CONTROL | DESKTOP_READOBJECTS | DESKTOP_WRITEOBJECTS);
        if (default_security) {
            const auto label = log_label(default_security, "Original Default desktop");
            const bool compatible = !edge_broker ||
                (label.first == SECURITY_MANDATORY_LOW_RID && label.second == SYSTEM_MANDATORY_LABEL_NO_WRITE_UP &&
                 sandbox_desktop_aces(default_security, sandbox_aces));
            CloseDesktop(default_security);
            if (!compatible) {
                SetLastError(ERROR_INVALID_SECURITY_DESCR);
                return false;
            }
        } else {
            std::fprintf(stderr, "Default desktop security handle unavailable (%lu)\n",
                         static_cast<unsigned long>(GetLastError()));
            if (edge_broker) return false;
        }

        // The logon launcher needs the account on this station and desktop.
        // Test the actual medium token instead of assuming its SID.
        LocalHandle thread_token;
        if (!DuplicateTokenEx(token, TOKEN_QUERY | TOKEN_IMPERSONATE, nullptr, SecurityImpersonation,
                              TokenImpersonation, &thread_token.value)) return false;
        const HWINSTA label_station = OpenWindowStationW(station_name, FALSE, READ_CONTROL);
        if (label_station) {
            log_label(label_station, "WinSta0");
            CloseWindowStation(label_station);
        } else {
            std::fprintf(stderr, "WinSta0 label handle unavailable (%lu)\n", static_cast<unsigned long>(GetLastError()));
        }
        const DWORD access_error = access_with(thread_token.value, station_name);
        std::fprintf(stderr, "Recipe account WinSta0 full access: %lu\n", static_cast<unsigned long>(access_error));
        if (access_error && !grant_station) {
            SetLastError(access_error);
            return false;
        }
        if (access_error && access_error != ERROR_ACCESS_DENIED) {
            SetLastError(access_error);
            return false;
        }
        if (access_error) {
            station = OpenWindowStationW(station_name, FALSE, READ_CONTROL | WRITE_DAC);
            if (!station) return false;
            SECURITY_INFORMATION security = DACL_SECURITY_INFORMATION;
            DWORD needed = 0;
            GetUserObjectSecurity(station, &security, nullptr, 0, &needed);
            if (!needed || needed > 65536) return false;
            station_descriptor.resize(needed);
            if (!GetUserObjectSecurity(station, &security, station_descriptor.data(), needed, &needed)) return false;
            BOOL has_dacl = FALSE, defaulted = FALSE;
            PACL station_original_dacl = nullptr;
            DWORD err = ERROR_SUCCESS;
            if (!GetSecurityDescriptorDacl(station_descriptor.data(), &has_dacl, &station_original_dacl, &defaulted))
                return false;
            PACL changed = nullptr;
            if (has_dacl && station_original_dacl) {
                EXPLICIT_ACCESSW access{};
                access.grfAccessPermissions = station_access;
                access.grfAccessMode = GRANT_ACCESS;
                BuildTrusteeWithSidW(&access.Trustee, account);
                err = SetEntriesInAclW(1, &access, station_original_dacl, &changed);
                if (err == ERROR_SUCCESS) {
                    SECURITY_DESCRIPTOR descriptor{};
                    // SetUserObjectSecurity updates the station, without
                    // SetSecurityInfo's automatic child ACE propagation.
                    station_changed = InitializeSecurityDescriptor(&descriptor, SECURITY_DESCRIPTOR_REVISION) &&
                        SetSecurityDescriptorDacl(&descriptor, TRUE, changed, FALSE) &&
                        SetUserObjectSecurity(station, &security, &descriptor);
                    if (!station_changed) err = GetLastError();
                }
            } else err = ERROR_INVALID_ACL;
            if (changed) LocalFree(changed);
            if (err != ERROR_SUCCESS) { SetLastError(err); return false; }
            std::fputs("WinSta0 access was granted temporarily to the isolated test account.\n", stderr);
            const DWORD retry = access_with(thread_token.value, station_name);
            std::fprintf(stderr, "Recipe account WinSta0 full access after grant: %lu\n", static_cast<unsigned long>(retry));
            if (retry) { SetLastError(retry); return false; }
        }

        LPWSTR sid_text = nullptr;
        if (!ConvertSidToStringSidW(account, &sid_text)) return false;
        const std::wstring sddl = std::wstring(L"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;") +
            sid_text + L")" + sandbox_aces + (edge_broker ? L"S:(ML;;NW;;;LW)" : L"S:(ML;;NW;;;ME)");
        LocalFree(sid_text);
        PSECURITY_DESCRIPTOR descriptor = nullptr;
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &descriptor, nullptr))
            return false;
        const std::wstring name = L"NoteViveRecipe-" + std::to_wstring(GetCurrentProcessId()) + L"-" +
            std::to_wstring(GetTickCount64());
        SECURITY_ATTRIBUTES attributes{sizeof(attributes), descriptor, FALSE};
        temporary = CreateDesktopW(name.c_str(), nullptr, nullptr, 0, desktop_access, &attributes);
        const auto create_error = temporary ? ERROR_SUCCESS : GetLastError();
        LocalFree(descriptor);
        if (!temporary) { SetLastError(create_error); return false; }
        const auto actual_label = log_label(temporary, "Recipe desktop");
        if (edge_broker && (actual_label.first != SECURITY_MANDATORY_LOW_RID ||
                            actual_label.second != SYSTEM_MANDATORY_LABEL_NO_WRITE_UP)) {
            SetLastError(ERROR_INVALID_SECURITY_DESCR);
            return false;
        }
        const DWORD desktop_check = access_with(thread_token.value, station_name, name.c_str());
        std::fprintf(stderr, "Recipe account desktop full access: %lu\n", static_cast<unsigned long>(desktop_check));
        if (desktop_check) { SetLastError(desktop_check); return false; }
        path = std::wstring(station_name) + L"\\" + name;
        if (!SwitchDesktop(temporary)) return false;
        switched = true;
        std::fputs(edge_broker ? "Using temporary Low input desktop matching Default's mandatory label.\n" :
            "Using temporary Medium input desktop.\n", stderr);
        return true;
    }
};

struct RecipeAccount {
    std::wstring name;
    std::wstring sid_string;
    std::vector<BYTE> sid_storage;
    wchar_t password[41]{};
    LocalHandle token;
    bool created = false, launch_succeeded = false, profile_quiet = true;

    ~RecipeAccount() {
        if (!cleanup()) std::fputs("Unable to remove test account or profile.\n", stderr);
    }
    PSID sid() { return sid_storage.empty() ? nullptr : sid_storage.data(); }
    bool join_local_users() {
        wchar_t computer[MAX_COMPUTERNAME_LENGTH + 1]{};
        DWORD computer_size = static_cast<DWORD>(sizeof(computer) / sizeof(wchar_t));
        if (!GetComputerNameW(computer, &computer_size)) return false;
        const std::wstring qualified = std::wstring(computer) + L"\\" + name;
        DWORD sid_size = 0, domain_size = 0;
        SID_NAME_USE use{};
        LookupAccountNameW(nullptr, qualified.c_str(), nullptr, &sid_size, nullptr, &domain_size, &use);
        if (!sid_size || sid_size > SECURITY_MAX_SID_SIZE || !domain_size || domain_size > 1024) return false;
        sid_storage.resize(sid_size);
        std::wstring domain(domain_size, L'\0');
        if (!LookupAccountNameW(nullptr, qualified.c_str(), sid(), &sid_size, domain.data(), &domain_size, &use))
            return false;
        if (use != SidTypeUser || !IsValidSid(sid())) { SetLastError(ERROR_INVALID_SID); return false; }
        BYTE builtin_users[SECURITY_MAX_SID_SIZE]{};
        DWORD builtin_size = sizeof(builtin_users);
        if (!CreateWellKnownSid(WinBuiltinUsersSid, nullptr, builtin_users, &builtin_size)) return false;
        wchar_t group[256]{}, group_domain[256]{};
        DWORD group_size = 256, group_domain_size = 256;
        if (!LookupAccountSidW(nullptr, builtin_users, group, &group_size, group_domain, &group_domain_size, &use))
            return false;
        LOCALGROUP_MEMBERS_INFO_0 member{sid()};
        const DWORD status = NetLocalGroupAddMembers(nullptr, group, 0, reinterpret_cast<BYTE*>(&member), 1);
        if (status == NERR_Success || status == ERROR_MEMBER_IN_ALIAS) return true;
        SetLastError(status);
        return false;
    }
    bool cleanup() {
        SecureZeroMemory(password, sizeof(password));
        if (token.value) {
            CloseHandle(token.value);
            token.value = nullptr;
        }
        if (launch_succeeded && profile_quiet && !sid_string.empty()) {
            bool deleted = false;
            for (unsigned n = 0; n < 20 && !deleted; ++n) {
                deleted = DeleteProfileW(sid_string.c_str(), nullptr, nullptr) != FALSE;
                if (!deleted) {
                    const auto error = GetLastError();
                    if (error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND) deleted = true;
                    else if (n == 19) std::fprintf(stderr, "DeleteProfile failed: %lu\n", static_cast<unsigned long>(error));
                    else Sleep(100);
                }
            }
            if (deleted) launch_succeeded = false;
        }
        if (created) {
            const auto status = NetUserDel(nullptr, name.c_str());
            if (status == NERR_Success || status == NERR_UserNotFound) created = false;
            else std::fprintf(stderr, "NetUserDel failed: %lu\n", static_cast<unsigned long>(status));
        }
        return !created && !launch_succeeded;
    }
    bool start() {
        BYTE random[40]{};
        if (BCryptGenRandom(nullptr, random, sizeof(random), BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0) {
            SetLastError(ERROR_GEN_FAILURE);
            return false;
        }
        constexpr wchar_t hex[] = L"0123456789abcdef";
        name = L"nvrecipe-";
        for (unsigned n = 0; n < 5; ++n) {
            name += hex[random[n] >> 4];
            name += hex[random[n] & 0xf];
        }
        constexpr wchar_t alphabet[] = L"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#%+-";
        password[0] = L'N'; password[1] = L'v'; password[2] = L'2'; password[3] = L'!';
        for (unsigned n = 4; n < 39; ++n) password[n] = alphabet[random[n + 1] % (sizeof(alphabet) / sizeof(wchar_t) - 1)];
        SecureZeroMemory(random, sizeof(random));
        USER_INFO_1 account{};
        account.usri1_name = name.data();
        account.usri1_password = password;
        account.usri1_priv = USER_PRIV_USER;
        account.usri1_flags = UF_NORMAL_ACCOUNT | UF_SCRIPT | UF_DONT_EXPIRE_PASSWD;
        DWORD bad = 0;
        const DWORD status = NetUserAdd(nullptr, 1, reinterpret_cast<BYTE*>(&account), &bad);
        if (status != NERR_Success) { SetLastError(status); return false; }
        created = true;
        if (!join_local_users()) return false;
        if (!LogonUserW(name.c_str(), L".", password, LOGON32_LOGON_INTERACTIVE, LOGON32_PROVIDER_DEFAULT,
                        &token.value)) return false;
        DWORD bytes = 0;
        GetTokenInformation(token.value, TokenUser, nullptr, 0, &bytes);
        std::vector<BYTE> user(bytes && bytes <= 4096 ? bytes : 0);
        if (user.empty() || !GetTokenInformation(token.value, TokenUser, user.data(), bytes, &bytes)) return false;
        auto account_sid = reinterpret_cast<TOKEN_USER*>(user.data())->User.Sid;
        if (!IsValidSid(account_sid) || !EqualSid(sid(), account_sid)) {
            SetLastError(ERROR_INVALID_SID);
            return false;
        }
        LPWSTR text = nullptr;
        if (!ConvertSidToStringSidW(sid(), &text)) return false;
        sid_string = text;
        LocalFree(text);

        TOKEN_ELEVATION elevation{};
        if (!GetTokenInformation(token.value, TokenElevation, &elevation, sizeof(elevation), &bytes)) return false;
        if (elevation.TokenIsElevated) { SetLastError(ERROR_ACCESS_DENIED); return false; }
        bytes = 0;
        GetTokenInformation(token.value, TokenIntegrityLevel, nullptr, 0, &bytes);
        std::vector<BYTE> integrity(bytes && bytes <= 4096 ? bytes : 0);
        if (integrity.empty() || !GetTokenInformation(token.value, TokenIntegrityLevel, integrity.data(), bytes, &bytes))
            return false;
        auto level = reinterpret_cast<TOKEN_MANDATORY_LABEL*>(integrity.data())->Label.Sid;
        if (!IsWellKnownSid(level, WinMediumLabelSid)) { SetLastError(ERROR_ACCESS_DENIED); return false; }

        bytes = 0;
        GetTokenInformation(token.value, TokenGroups, nullptr, 0, &bytes);
        std::vector<BYTE> groups(bytes && bytes <= 65536 ? bytes : 0);
        if (groups.empty() || !GetTokenInformation(token.value, TokenGroups, groups.data(), bytes, &bytes)) return false;
        const auto* memberships = reinterpret_cast<const TOKEN_GROUPS*>(groups.data());
        for (DWORD n = 0; n < memberships->GroupCount; ++n) {
            const auto group = memberships->Groups[n];
            if (IsWellKnownSid(group.Sid, WinBuiltinAdministratorsSid) && (group.Attributes & SE_GROUP_ENABLED)) {
                SetLastError(ERROR_ACCESS_DENIED);
                return false;
            }
        }
        std::fputs("Fresh local recipe account verified: integrity=0x2000 elevated=0 administrators_disabled=1\n", stderr);
        return true;
    }
};

bool grant_stage_access(const wchar_t* path, PSID account, bool write) {
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    PACL current = nullptr, changed = nullptr;
    DWORD error = GetNamedSecurityInfoW(const_cast<LPWSTR>(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                        nullptr, nullptr, &current, nullptr, &descriptor);
    if (error == ERROR_SUCCESS && current) {
        EXPLICIT_ACCESSW permission{};
        permission.grfAccessPermissions = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE;
        if (write) permission.grfAccessPermissions |= FILE_GENERIC_WRITE;
        permission.grfAccessMode = GRANT_ACCESS;
        permission.grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT;
        BuildTrusteeWithSidW(&permission.Trustee, account);
        error = SetEntriesInAclW(1, &permission, current, &changed);
        if (error == ERROR_SUCCESS)
            error = SetNamedSecurityInfoW(const_cast<LPWSTR>(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                          nullptr, nullptr, changed, nullptr);
    } else if (error == ERROR_SUCCESS) error = ERROR_INVALID_ACL;
    if (changed) LocalFree(changed);
    if (descriptor) LocalFree(descriptor);
    if (error != ERROR_SUCCESS) SetLastError(error);
    return error == ERROR_SUCCESS;
}

bool stage_directory(const wchar_t* directory) {
    // Only the fixed, fresh staging layout created by the hosted recipe is
    // eligible for an ACL grant. Never act on a caller's checkout.
    wchar_t public_directory[MAX_PATH]{};
    const auto n = GetEnvironmentVariableW(L"PUBLIC", public_directory, MAX_PATH);
    if (!n || n >= MAX_PATH) return false;
    constexpr wchar_t prefix[] = L"\\notevive-interactive-";
    const std::wstring expected = std::wstring(public_directory) + prefix;
    const std::wstring path(directory);
    if (path.compare(0, expected.size(), expected) != 0 || path.size() != expected.size() + 32) return false;
    if (path.find_first_not_of(L"0123456789abcdef", expected.size()) != std::wstring::npos) return false;
    const auto normal_directory = [](const std::wstring& p) {
        const auto flags = GetFileAttributesW(p.c_str());
        return flags != INVALID_FILE_ATTRIBUTES && (flags & FILE_ATTRIBUTE_DIRECTORY) &&
            !(flags & FILE_ATTRIBUTE_REPARSE_POINT);
    };
    return normal_directory(public_directory) && normal_directory(path) && normal_directory(path + L"\\out");
}

bool token_part(HANDLE token, TOKEN_INFORMATION_CLASS kind, std::vector<BYTE>& value) {
    DWORD size = 0;
    GetTokenInformation(token, kind, nullptr, 0, &size);
    if (!size || size > 65536) return false;
    value.resize(size);
    return GetTokenInformation(token, kind, value.data(), size, &size);
}

// The filtered arm only compares identities. It does not create a logon,
// write a namespace ACL, enable token privileges or load/delete a profile.
struct FilteredIdentity {
    std::vector<BYTE> user, logon;
    LUID auth{};
    DWORD session = UINT32_MAX;

    bool read(HANDLE token) {
        TOKEN_STATISTICS statistics{};
        DWORD size = 0;
        if (!GetTokenInformation(token, TokenStatistics, &statistics, sizeof(statistics), &size) ||
                statistics.TokenType != TokenPrimary ||
                !GetTokenInformation(token, TokenSessionId, &session, sizeof(session), &size) ||
                session == 0 || session == UINT32_MAX) return false;
        auth = statistics.AuthenticationId;
        std::vector<BYTE> user_info, logon_info;
        if (!token_part(token, TokenUser, user_info) || !token_part(token, TokenLogonSid, logon_info)) return false;
        const auto* groups = reinterpret_cast<const TOKEN_GROUPS*>(logon_info.data());
        constexpr DWORD active_logon = SE_GROUP_LOGON_ID | SE_GROUP_ENABLED;
        if (groups->GroupCount != 1 || (groups->Groups[0].Attributes & active_logon) != active_logon ||
                (groups->Groups[0].Attributes & SE_GROUP_USE_FOR_DENY_ONLY)) return false;
        const auto copy_sid = [](PSID sid, std::vector<BYTE>& bytes) {
            if (!IsValidSid(sid)) return false;
            bytes.resize(GetLengthSid(sid));
            return CopySid(static_cast<DWORD>(bytes.size()), bytes.data(), sid) != FALSE;
        };
        return copy_sid(reinterpret_cast<const TOKEN_USER*>(user_info.data())->User.Sid, user) &&
               copy_sid(groups->Groups[0].Sid, logon);
    }

    bool same(const FilteredIdentity& other) const {
        const bool session_ok = session == other.session, user_ok = user == other.user, logon_ok = logon == other.logon;
        const bool auth_ok = auth.LowPart == other.auth.LowPart && auth.HighPart == other.auth.HighPart;
        if (!session_ok || !auth_ok || !user_ok || !logon_ok)
            std::fprintf(stderr, "Filtered identity mismatch: session=%d auth_luid=%d user_sid=%d logon_sid=%d.\n",
                         session_ok, auth_ok, user_ok, logon_ok);
        return session_ok && auth_ok && user_ok && logon_ok;
    }

    std::wstring digest() const {
        // Compare the same data inside the process without writing or
        // printing SID/logon identifiers in the CI artifacts.
        std::vector<BYTE> bytes;
        const auto add = [&](const void* data, size_t size) {
            const auto* first = static_cast<const BYTE*>(data);
            bytes.insert(bytes.end(), first, first + size);
        };
        add(&session, sizeof(session));
        add(&auth.LowPart, sizeof(auth.LowPart));
        add(&auth.HighPart, sizeof(auth.HighPart));
        const auto user_size = static_cast<DWORD>(user.size());
        add(&user_size, sizeof(user_size));
        add(user.data(), user.size());
        add(logon.data(), logon.size());
        BCRYPT_ALG_HANDLE algorithm = nullptr;
        if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0) return {};
        BYTE hash[32]{};
        const NTSTATUS status = BCryptHash(algorithm, nullptr, 0, bytes.data(),
                                          static_cast<ULONG>(bytes.size()), hash, sizeof(hash));
        BCryptCloseAlgorithmProvider(algorithm, 0);
        if (status != 0) return {};
        std::wstring hex;
        for (const BYTE byte : hash) {
            constexpr wchar_t digits[] = L"0123456789abcdef";
            hex += digits[byte >> 4];
            hex += digits[byte & 15];
        }
        return hex;
    }
};

bool same_process_session(DWORD pid, DWORD token_session) {
    DWORD session = UINT32_MAX;
    return ProcessIdToSessionId(pid, &session) && session == token_session;
}

bool filtered_token(HANDLE token, PSID administrators) {
    const auto query_failed = [](const char* name) {
        std::fprintf(stderr, "Filtered token query %s failed (Windows error %lu).\n", name,
                     static_cast<unsigned long>(GetLastError()));
        return false;
    };
    const auto rejected = [](const char* name, DWORD mask) {
        std::fprintf(stderr, "Filtered token rejected at %s: 0x%lx.\n", name, static_cast<unsigned long>(mask));
        return false;
    };
    TOKEN_ELEVATION elevation{};
    DWORD received = 0, ui_access = 1, app_container = 1;
    if (!GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &received))
        return query_failed("TokenElevation");
    if (elevation.TokenIsElevated) return rejected("TokenElevation", elevation.TokenIsElevated);
    if (!GetTokenInformation(token, TokenUIAccess, &ui_access, sizeof(ui_access), &received))
        return query_failed("TokenUIAccess");
    if (ui_access) return rejected("TokenUIAccess", ui_access);
    if (!GetTokenInformation(token, TokenIsAppContainer, &app_container, sizeof(app_container), &received))
        return query_failed("TokenIsAppContainer");
    if (app_container) return rejected("TokenIsAppContainer", app_container);
    std::vector<BYTE> level, groups, privileges;
    if (!token_part(token, TokenIntegrityLevel, level)) return query_failed("TokenIntegrityLevel");
    if (!token_part(token, TokenGroups, groups)) return query_failed("TokenGroups");
    if (!token_part(token, TokenPrivileges, privileges)) return query_failed("TokenPrivileges");
    const auto integrity = reinterpret_cast<const TOKEN_MANDATORY_LABEL*>(level.data())->Label.Sid;
    if (!IsWellKnownSid(integrity, WinMediumLabelSid)) {
        const auto count = IsValidSid(integrity) ? *GetSidSubAuthorityCount(integrity) : 0;
        return rejected("TokenIntegrityLevel RID", count ? *GetSidSubAuthority(integrity, count - 1) : 0);
    }
    bool deny_only = false;
    const auto* group_info = reinterpret_cast<const TOKEN_GROUPS*>(groups.data());
    for (DWORD i = 0; i < group_info->GroupCount; ++i) {
        const auto& group = group_info->Groups[i];
        if (EqualSid(group.Sid, administrators)) {
            constexpr DWORD mask = SE_GROUP_ENABLED | SE_GROUP_ENABLED_BY_DEFAULT | SE_GROUP_USE_FOR_DENY_ONLY;
            if ((group.Attributes & mask) != SE_GROUP_USE_FOR_DENY_ONLY)
                return rejected("Administrators group attributes", group.Attributes & mask);
            deny_only = true;
        }
    }
    LUID traverse{};
    if (!deny_only) return rejected("Administrators group present", 0);
    if (!LookupPrivilegeValueW(nullptr, L"SeChangeNotifyPrivilege", &traverse))
        return query_failed("LookupPrivilegeValueW for the traverse privilege");
    const auto* privilege_info = reinterpret_cast<const TOKEN_PRIVILEGES*>(privileges.data());
    for (DWORD i = 0; i < privilege_info->PrivilegeCount; ++i) {
        const auto& privilege = privilege_info->Privileges[i];
        if ((privilege.Attributes & SE_PRIVILEGE_ENABLED) &&
                (privilege.Luid.LowPart != traverse.LowPart || privilege.Luid.HighPart != traverse.HighPart))
            return rejected("unexpected enabled privilege attributes", privilege.Attributes);
    }
    return true;
}

bool normal_file(const std::wstring& path) {
    const DWORD flags = GetFileAttributesW(path.c_str());
    return flags != INVALID_FILE_ATTRIBUTES && !(flags & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT));
}

int filtered_child(const wchar_t* expected) {
    wchar_t directory[MAX_PATH]{};
    const DWORD length = GetCurrentDirectoryW(MAX_PATH, directory);
    require(length && length < MAX_PATH && stage_directory(directory), "invalid filtered child staging directory");
    if (!_wfreopen(L"out\\filtered-child.log", L"wb", stderr)) return 3;
    LocalHandle token;
    BYTE administrators[SECURITY_MAX_SID_SIZE]{};
    DWORD size = sizeof(administrators);
    BOOL in_job = FALSE;
    FilteredIdentity identity;
    require(IsProcessInJob(GetCurrentProcess(), nullptr, &in_job) && in_job &&
            CreateWellKnownSid(WinBuiltinAdministratorsSid, nullptr, administrators, &size) &&
            OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.value) && filtered_token(token.value, administrators) &&
            identity.read(token.value) && same_process_session(GetCurrentProcessId(), identity.session),
            "filtered child must run in the recipe job with a Medium non-elevated token");
    const auto actual = identity.digest();
    require(actual.size() == 64 && actual == expected, "filtered child user/logon/session/authentication identity changed");
    std::fputs("Filtered child verified: Medium, non-elevated, Administrators DenyOnly, same user/logon/session/LUID.\n", stderr);
    std::fflush(stderr);

    wchar_t system[MAX_PATH]{};
    const UINT system_size = GetSystemDirectoryW(system, MAX_PATH);
    require(system_size && system_size < MAX_PATH, "resolve Windows PowerShell location");
    const std::wstring power_shell = std::wstring(system) + L"\\WindowsPowerShell\\v1.0\\powershell.exe";
    require(normal_file(L"edge-bootstrap.ps1") && normal_file(power_shell), "locate filtered Edge bootstrap");
    // Only the host markers already required by the parent are passed on,
    // independently of any credentials in its GitHub Actions environment.
    require(SetEnvironmentVariableW(L"GITHUB_ACTIONS", L"true") &&
            SetEnvironmentVariableW(L"RUNNER_ENVIRONMENT", L"github-hosted"),
            "set the two hosted recipe markers");
    std::wstring command = L"\"" + power_shell +
        L"\" -NoProfile -NonInteractive -File .\\edge-bootstrap.ps1 -RecipeCase EdgeFiltered";
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION next{};
    require(CreateProcessW(power_shell.c_str(), command.data(), nullptr, nullptr, FALSE,
                            CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr, directory, &startup, &next),
            "start the filtered Edge bootstrap without changing its token");
    LocalHandle process{next.hProcess}, thread{next.hThread}, bootstrap_token;
    FilteredIdentity bootstrap;
    require(OpenProcessToken(process.value, TOKEN_QUERY, &bootstrap_token.value) &&
            filtered_token(bootstrap_token.value, administrators) &&
            bootstrap.read(bootstrap_token.value) && bootstrap.same(identity) &&
            same_process_session(next.dwProcessId, bootstrap.session),
            "the Edge PowerShell bootstrap did not inherit the verified token");
    AllowSetForegroundWindow(next.dwProcessId);
    require(ResumeThread(thread.value) != static_cast<DWORD>(-1), "resume the verified PowerShell bootstrap");
    DWORD exit_code = 1;
    require(WaitForSingleObject(process.value, 90000) == WAIT_OBJECT_0 &&
            GetExitCodeProcess(process.value, &exit_code), "filtered Edge bootstrap deadline");
    return exit_code == 0 ? 0 : 1;
}

int launch_filtered(const wchar_t* directory) {
    const auto failure = [](const char* operation) {
        std::fprintf(stderr, "Filtered Edge: %s (Windows error %lu).\n", operation,
                     static_cast<unsigned long>(GetLastError()));
        return 1;
    };
    if (!hosted_recipe() || !stage_directory(directory))
        return failure("requires GitHub-hosted CI and a fresh private staging directory");
    const std::wstring executable = std::wstring(directory) + L"\\external-target-test.exe";
    if (!normal_file(executable) || !normal_file(std::wstring(directory) + L"\\edge-bootstrap.ps1"))
        return failure("invalid staged executable or bootstrap");
    LocalHandle runner, filtered;
    constexpr DWORD rights = TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY | TOKEN_ADJUST_DEFAULT;
    TOKEN_ELEVATION elevation{};
    DWORD received = 0;
    FilteredIdentity original, selected;
    BYTE administrators[SECURITY_MAX_SID_SIZE]{}, medium[SECURITY_MAX_SID_SIZE]{};
    DWORD administrators_size = sizeof(administrators), medium_size = sizeof(medium);
    if (!OpenProcessToken(GetCurrentProcess(), rights, &runner.value) ||
            !GetTokenInformation(runner.value, TokenElevation, &elevation, sizeof(elevation), &received) ||
            !elevation.TokenIsElevated ||
            !original.read(runner.value) || !same_process_session(GetCurrentProcessId(), original.session) ||
            !CreateWellKnownSid(WinBuiltinAdministratorsSid, nullptr, administrators, &administrators_size) ||
            !CreateWellKnownSid(WinMediumLabelSid, nullptr, medium, &medium_size))
        return failure("cannot identify the elevated interactive runner");
    SID_AND_ATTRIBUTES disable{administrators, 0};
    // Preserve the historical filtered launcher's LUA and privilege flags.
    constexpr DWORD flags = DISABLE_MAX_PRIVILEGE | LUA_TOKEN;
    if (!CreateRestrictedToken(runner.value, flags, 1, &disable, 0, nullptr, 0, nullptr, &filtered.value))
        return failure("CreateRestrictedToken");
    TOKEN_MANDATORY_LABEL mandatory{{medium, SE_GROUP_INTEGRITY}};
    if (!SetTokenInformation(filtered.value, TokenIntegrityLevel, &mandatory, sizeof(mandatory) + medium_size))
        return failure("set filtered token integrity to Medium");
    if (!filtered_token(filtered.value, administrators)) return failure("verify restricted runner token");
    if (!selected.read(filtered.value)) return failure("read restricted runner token identity");
    if (!selected.same(original)) return failure("preserve the original runner logon identity");
    const auto expected = original.digest();
    if (expected.size() != 64) return failure("hash the original logon identity");

    RecipeDesktop desktop;
    LocalHandle job{CreateJobObjectW(nullptr, nullptr)};
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!job.value || !SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
        return failure("create the kill-on-close descendant job");
    if (!desktop.start(filtered.value, selected.user.data(), true, false))
        return failure("open the Low test desktop without changing WinSta0 access");
    struct Environment {
        LPVOID value = nullptr;
        ~Environment() { if (value) DestroyEnvironmentBlock(value); }
    } environment;
    if (!CreateEnvironmentBlock(&environment.value, filtered.value, FALSE))
        return failure("prepare the existing profile environment without inheriting runner variables");
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.lpDesktop = desktop.path.data();
    std::wstring command = L"\"" + executable + L"\" --edge-filtered-child " + expected;
    PROCESS_INFORMATION child{};
    if (!CreateProcessAsUserW(filtered.value, executable.c_str(), command.data(), nullptr, nullptr, FALSE,
            CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT, environment.value, directory, &startup, &child))
        return failure("CreateProcessAsUserW for the filtered token");
    LocalHandle child_process{child.hProcess}, child_thread{child.hThread}, child_token;
    if (!AssignProcessToJobObject(job.value, child_process.value)) {
        const auto result = failure("assign the suspended process to the cleanup job");
        TerminateProcess(child_process.value, 1);
        WaitForSingleObject(child_process.value, 3000);
        return result;
    }
    FilteredIdentity started;
    const bool checked = OpenProcessToken(child_process.value, TOKEN_QUERY, &child_token.value) &&
        filtered_token(child_token.value, administrators) && started.read(child_token.value) &&
        started.same(original) && same_process_session(child.dwProcessId, started.session);
    DWORD exit_code = 1;
    bool collected = false;
    if (checked) {
        std::fputs("Filtered launch verified: Medium, non-elevated, Administrators DenyOnly, same user/logon/session/LUID.\n", stderr);
        AllowSetForegroundWindow(child.dwProcessId);
        if (ResumeThread(child_thread.value) != static_cast<DWORD>(-1)) {
            collected = WaitForSingleObject(child_process.value, 95000) == WAIT_OBJECT_0 &&
                        GetExitCodeProcess(child_process.value, &exit_code);
            if (collected)
                std::fprintf(stderr, "Filtered test process exit: 0x%08lx (%lu)\n",
                             static_cast<unsigned long>(exit_code), static_cast<unsigned long>(exit_code));
            else std::fputs("Filtered Edge recipe did not finish before its deadline.\n", stderr);
        } else failure("resume the filtered Edge recipe");
    } else std::fputs("Suspended Edge process has an unexpected token or logon identity.\n", stderr);

    if (!TerminateJobObject(job.value, 1)) return failure("stop the filtered recipe job");
    const bool drained = within([&] {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
        return QueryInformationJobObject(job.value, JobObjectBasicAccountingInformation,
                   &accounting, sizeof(accounting), nullptr) && accounting.ActiveProcesses == 0;
    }, 3000);
    if (!drained) return failure("verify that the filtered Edge job has no live descendants");
    if (!desktop.restore()) return failure("restore the original input desktop");
    return collected && exit_code == 0 ? 0 : 1;
}

struct RecipeProcessCleanup {
    RecipeAccount& account;
    DWORD session = UINT32_MAX;
    bool active = false, unconfirmed_stop = false;

    ~RecipeProcessCleanup() {
        if (active) stop();
    }

    void terminate(DWORD pid, ULONGLONG cutoff) {
        // Recheck identity after opening the handle: WTS's PID could have
        // referred to a process that exited while we were enumerating.
        constexpr DWORD access = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | SYNCHRONIZE;
        LocalHandle process, token;
        const auto open_query_handles = [&] {
            if (!process.value) process.value = OpenProcess(access, FALSE, pid);
            return process.value && OpenProcessToken(process.value, TOKEN_QUERY, &token.value);
        };
        bool queryable = open_query_handles();
        if (!queryable && GetLastError() == ERROR_ACCESS_DENIED && ImpersonateLoggedOnUser(account.token.value)) {
            queryable = open_query_handles();
            if (!RevertToSelf()) std::terminate();
        }
        DWORD length = 0, token_session = UINT32_MAX;
        if (!queryable || WaitForSingleObject(process.value, 0) == WAIT_OBJECT_0 ||
            !GetTokenInformation(token.value, TokenSessionId, &token_session, sizeof(token_session), &length) ||
            token_session != session)
            return;
        length = 0;
        GetTokenInformation(token.value, TokenUser, nullptr, 0, &length);
        std::vector<BYTE> user(length && length <= 4096 ? length : 0);
        if (user.empty() || !GetTokenInformation(token.value, TokenUser, user.data(), length, &length)) return;
        const auto sid = reinterpret_cast<const TOKEN_USER*>(user.data())->User.Sid;
        if (!IsValidSid(sid) || !EqualSid(account.sid(), sid)) return;
        // Termination is asynchronous, including a race with normal exit.
        // Verify the same process handle before closing it.
        TerminateProcess(process.value, 1);
        const auto now = GetTickCount64();
        const DWORD remaining_ms = now < cutoff ? static_cast<DWORD>(cutoff - now) : 0;
        if (WaitForSingleObject(process.value, remaining_ms) != WAIT_OBJECT_0) unconfirmed_stop = true;
    }

    bool stop() {
        if (!active) return true;
        const auto cutoff = GetTickCount64() + 3000;
        do {
            PWTS_PROCESS_INFOW entries = nullptr;
            DWORD length = 0, remaining = 0;
            if (!WTSEnumerateProcessesW(WTS_CURRENT_SERVER_HANDLE, 0, 1, &entries, &length)) break;
            for (DWORD n = 0; n < length; ++n) {
                const auto& entry = entries[n];
                if (entry.SessionId == session && entry.pUserSid && EqualSid(account.sid(), entry.pUserSid)) {
                    ++remaining;
                    terminate(entry.ProcessId, cutoff);
                }
            }
            WTSFreeMemory(entries);
            if (!remaining && !unconfirmed_stop) {
                active = false;
                account.profile_quiet = true;
                std::fputs("Edge account process cleanup: verified zero remaining.\n", stderr);
                return true;
            }
            if (unconfirmed_stop) break;
            Sleep(100);
        } while (GetTickCount64() < cutoff);
        std::fputs("Edge account process cleanup could not verify zero remaining; profile deletion skipped.\n", stderr);
        return false;
    }
};

int launch_standard(const wchar_t* executable, const wchar_t* arguments, const wchar_t* directory,
                    ACCESS_MASK edge_access, bool edge_owns_jobs) {
    if (!hosted_recipe()) {
        std::fputs("Temporary local accounts are only used on hosted GitHub Actions.\n", stderr);
        return 1;
    }
    if (!stage_directory(directory)) {
        std::fputs("The standard recipe needs a fresh private staging directory.\n", stderr);
        return 1;
    }
    const bool edge_broker = edge_access && std::wcscmp(arguments, L"--edge-namespace-control") != 0;
    if (edge_broker && edge_owns_jobs) {
        std::fputs("The logon namespace comparison requires the enclosing recipe job.\n", stderr);
        return 1;
    }
    // Declare cleanup in reverse order: stop processes, restore desktop ACLs,
    // then remove the isolated profile and account.
    RecipeAccount account;
    RecipeDesktop desktop;
    RecipeNamespace named_objects;
    RecipeNamespace app_objects(RecipeNamespace::Kind::app_container);
    LocalHandle job;
    LocalHandle child_process, child_thread;
    RecipeProcessCleanup browser_processes{account};
    const auto failure = [](const char* operation) {
        const auto error = GetLastError();
        std::fprintf(stderr, "%s failed (Windows error %lu)\n", operation, static_cast<unsigned long>(error));
        return 1;
    };
    if (!account.start()) return failure("Create and verify local standard test account");
    const std::wstring output = std::wstring(directory) + L"\\out";
    if (!grant_stage_access(directory, account.sid(), false) || !grant_stage_access(output.c_str(), account.sid(), true))
        return failure("Grant access to isolated test files");

    if (!edge_owns_jobs) {
        job.value = CreateJobObjectW(nullptr, nullptr);
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!job.value || !SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
            return failure("SetInformationJobObject");
    }
    if (!desktop.start(account.token.value, account.sid(), edge_broker))
        return failure("Prepare temporary Windows input desktop");
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.lpDesktop = desktop.path.data();
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_HIDE;
    // The child writes its diagnostics inside out, avoiding handle inheritance
    // across the two logon sessions.
    PROCESS_INFORMATION child{};
    std::wstring command = L"\"" + std::wstring(executable) + L"\" " + arguments;
    if (!CreateProcessWithLogonW(account.name.c_str(), L".", account.password, LOGON_WITH_PROFILE,
                                 executable, command.data(), CREATE_SUSPENDED | CREATE_NO_WINDOW,
                                 nullptr, directory, &startup, &child))
        return failure("CreateProcessWithLogonW for the standard account");
    account.launch_succeeded = true;
    SecureZeroMemory(account.password, sizeof(account.password));
    child_process.value = child.hProcess;
    child_thread.value = child.hThread;
    const auto launcher_session = report_session("recipe_launcher", GetCurrentProcessId(), GetCurrentProcess());
    const auto child_session = report_session("recipe_child", child.dwProcessId, child.hProcess);
    if (edge_owns_jobs) {
        BOOL inherited = FALSE;
        if (child_session == UINT32_MAX || child_session != launcher_session ||
            !IsProcessInJob(child_process.value, nullptr, &inherited) || inherited) {
            TerminateProcess(child_process.value, 1);
            account.profile_quiet = WaitForSingleObject(child_process.value, 1000) == WAIT_OBJECT_0;
            std::fputs("Cannot verify the suspended Edge recipe is in the same session outside any outer job.\n", stderr);
            return 1;
        }
        browser_processes.session = child_session;
        browser_processes.active = true;
        account.profile_quiet = false;
        std::fputs("Edge recipe starts with its own sandbox jobs, without a recipe job.\n", stderr);
    } else if (!AssignProcessToJobObject(job.value, child_process.value)) {
        const auto code = failure("AssignProcessToJobObject");
        TerminateProcess(child_process.value, 1);
        return code;
    }
    if (edge_access && !named_objects.start(child.dwProcessId, child_process.value,
                                            account.token.value, account.sid(), edge_access, edge_broker))
        return failure("Prepare the session namespace for the Edge recipe");
    if (edge_broker && !app_objects.start(child.dwProcessId, child_process.value, account.token.value,
                                          account.sid(), RecipeNamespace::with_subdirectory))
        return failure("Prepare the AppContainer session namespace for the Edge recipe");
    AllowSetForegroundWindow(child.dwProcessId);
    if (ResumeThread(child_thread.value) == static_cast<DWORD>(-1)) return failure("ResumeThread");
    if (WaitForSingleObject(child_process.value, 95000) != WAIT_OBJECT_0) {
        std::fputs("Ordinary Windows test process did not exit before its deadline.\n", stderr);
        return 1;
    }
    DWORD elapsed_code = 1;
    if (!GetExitCodeProcess(child_process.value, &elapsed_code)) return failure("GetExitCodeProcess");
    std::fprintf(stderr, "Standard test process exit: 0x%08lx (%lu)\n",
                 static_cast<unsigned long>(elapsed_code), static_cast<unsigned long>(elapsed_code));
    if (job.value) {
        if (!TerminateJobObject(job.value, 1)) return failure("Stop the recipe process job");
        const auto cutoff = GetTickCount64() + 3000;
        while (true) {
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
            if (!QueryInformationJobObject(job.value, JobObjectBasicAccountingInformation,
                                           &accounting, sizeof(accounting), nullptr))
                return failure("Verify the recipe process job is empty");
            if (!accounting.ActiveProcesses) break;
            if (GetTickCount64() >= cutoff) {
                std::fputs("Recipe process job is not empty at cleanup deadline.\n", stderr);
                return 1;
            }
            Sleep(20);
        }
    }
    if (!browser_processes.stop()) return 1;
    const bool restored_app = app_objects.restore();
    const bool restored_base = named_objects.restore();
    if (!restored_app || !restored_base) {
        std::fputs("Restoring the session named-object DACL failed.\n", stderr);
        return 1;
    }
    if (!desktop.restore()) {
        std::fputs("Restoring the original input desktop or station ACL failed.\n", stderr);
        return 1;
    }
    CloseHandle(child_process.value);
    child_process.value = nullptr;
    CloseHandle(child_thread.value);
    child_thread.value = nullptr;
    return account.cleanup() && elapsed_code == 0 ? 0 : 1;
}

std::wstring text(HWND edit) {
    // Reading the synthetic fixture, never a third-party document.
    wchar_t value[256]{};
    DWORD_PTR ignored = 0;
    require(SendMessageTimeoutW(edit, WM_GETTEXT, 256, reinterpret_cast<LPARAM>(value),
                                SMTO_ABORTIFHUNG | SMTO_BLOCK, 100, &ignored), "read isolated fixture");
    return value;
}
const char* result_id(Result result);

struct NativeCaptureProbe {
    HWND window, edit;
    DWORD pid;
    struct Focus {
        bool desktop = false, foreground = false, active = false, caret_window = false, matching_thread = false;
        DWORD gui_flags = 0, gui_error = 0, desktop_error = 0;
    };
    Focus focus_now() const {
        Focus result;
        const auto input = OpenInputDesktop(0, FALSE, DESKTOP_READOBJECTS);
        result.desktop_error = input ? ERROR_SUCCESS : GetLastError();
        if (input) {
            wchar_t actual[256]{}, caller[256]{};
            DWORD length = 0;
            const auto thread = GetThreadDesktop(GetCurrentThreadId());
            result.desktop = thread &&
                GetUserObjectInformationW(input, UOI_NAME, actual, sizeof(actual), &length) &&
                GetUserObjectInformationW(thread, UOI_NAME, caller, sizeof(caller), &length) &&
                std::wcscmp(actual, caller) == 0;
            CloseDesktop(input);
        }
        result.foreground = GetForegroundWindow() == window;
        DWORD owner_pid = 0, edit_pid = 0;
        const auto tid = GetWindowThreadProcessId(window, &owner_pid);
        const auto edit_tid = GetWindowThreadProcessId(edit, &edit_pid);
        result.matching_thread = tid && tid == edit_tid && owner_pid == pid && edit_pid == pid;
        GUITHREADINFO gui{};
        gui.cbSize = sizeof(gui);
        if (tid && GetGUIThreadInfo(tid, &gui)) {
            result.gui_flags = gui.flags;
            result.active = gui.hwndActive == window;
            result.caret_window = gui.hwndFocus == edit && GetAncestor(edit, GA_ROOT) == window;
        } else result.gui_error = tid ? GetLastError() : ERROR_INVALID_WINDOW_HANDLE;
        return result;
    }
    static void log_focus(const char* phase, const Focus& f) {
        std::fprintf(stderr, "Native capture %s: input=%d input_error=%lu expected_foreground=%d active=%d "
            "expected_field=%d target_thread=%d gui_flags=0x%lx gui_error=%lu\n",
            phase, f.desktop, static_cast<unsigned long>(f.desktop_error), f.foreground, f.active,
            f.caret_window, f.matching_thread, static_cast<unsigned long>(f.gui_flags),
            static_cast<unsigned long>(f.gui_error));
    }
    void log_control() const {
        // Messages here only reach the known fictitious editor, never whichever
        // program happens to have foreground during the failure.
        DWORD actual = 0;
        wchar_t name[32]{};
        if (!edit || !GetWindowThreadProcessId(edit, &actual) || actual != pid ||
            GetAncestor(edit, GA_ROOT) != window || !RealGetWindowClassW(edit, name, 32) ||
            CompareStringOrdinal(name, -1, L"EDIT", -1, TRUE) != CSTR_EQUAL) {
            std::fputs("Native capture fixture is no longer the known EDIT.\n", stderr);
            return;
        }
        const auto timed = [&](const char* label, UINT message, WPARAM w, LPARAM l, DWORD_PTR& value) {
            SetLastError(ERROR_SUCCESS);
            const bool ok = SendMessageTimeoutW(edit, message, w, l,
                SMTO_ABORTIFHUNG | SMTO_BLOCK | SMTO_ERRORONEXIT, 100, &value) != 0;
            const DWORD error = ok ? ERROR_SUCCESS : GetLastError();
            std::fprintf(stderr, "Native capture diagnostic %s: ok=%d error=%lu\n",
                         label, ok, static_cast<unsigned long>(error));
            return ok;
        };
        DWORD first = MAXDWORD, last = MAXDWORD;
        DWORD_PTR ignored = 0, password = 0, size = 0, limit = 0;
        const bool pass = timed("password probe", EM_GETPASSWORDCHAR, 0, 0, password);
        const bool select = timed("caret probe", EM_GETSEL, reinterpret_cast<WPARAM>(&first),
                                  reinterpret_cast<LPARAM>(&last), ignored);
        const bool measure = timed("text-length probe", WM_GETTEXTLENGTH, 0, 0, size);
        const bool capacity = timed("limit probe", EM_GETLIMITTEXT, 0, 0, limit);
        std::fprintf(stderr, "Native capture fixture: visible=%d enabled=%d unicode=%d password=%d "
            "collapsed=%d position_valid=%d limit_valid=%d\n",
            IsWindowVisible(window) && IsWindowVisible(edit), IsWindowEnabled(window) && IsWindowEnabled(edit),
            IsWindowUnicode(edit) != 0, pass && password != 0, select && first != MAXDWORD && first == last,
            select && measure && last <= size, measure && capacity && size <= limit);
    }
};

Result capture(Target& target, HWND owner, const NativeCaptureProbe* probe = nullptr) {
    target.reset();
    Sleep(30); // Do not race the previous native test's worker shutdown.
    pump();
    const auto before = probe ? probe->focus_now() : NativeCaptureProbe::Focus{};
    const auto start = GetTickCount64();
    const auto status = target.capture(owner, probe ? probe->window : nullptr, probe ? probe->pid : 0);
    const bool completed = status != Result::pending || within([&] { return target.check() != Result::pending; });
    const auto result = status == Result::pending ? target.check() : status;
    if (probe && (!completed || result != Result::ready)) {
        std::fprintf(stderr, "Native capture start=%s final=%s waited_ms=%llu\n",
            result_id(status), result_id(result), static_cast<unsigned long long>(GetTickCount64() - start));
        NativeCaptureProbe::log_focus("before", before);
        NativeCaptureProbe::log_focus("after", probe->focus_now());
        probe->log_control();
    }
    require(completed, "capture deadline");
    return result;
}

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
    const NativeCaptureProbe probe{proc.first, field(proc.first, kFirst), child_process.dwProcessId};
    const auto initial = capture(target, owner, &probe);
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
        if (argc == 2 && std::wcscmp(argv[1], L"--edge-startup-preflight") == 0)
            return edge_startup_preflight();
        if (argc == 2 && std::wcscmp(argv[1], L"--edge-lowbox-trace") == 0) {
            if (!ordinary_token()) return 1;
            const auto session = report_session("edge_lowbox_trace", GetCurrentProcessId(), GetCurrentProcess());
            return observe_lowbox_creation(session) ? 0 : 1;
        }
        if (argc == 2 && std::wcscmp(argv[1], L"--edge-namespace-control") == 0)
            return edge_namespace_control();
        if (argc == 2 && std::wcscmp(argv[1], L"--environment") == 0) return environment();
        if (argc == 3 && std::wcscmp(argv[1], L"--launch-edge-filtered") == 0) return launch_filtered(argv[2]);
        if (argc == 3 && std::wcscmp(argv[1], L"--edge-filtered-child") == 0) return filtered_child(argv[2]);
        if ((argc == 5 || argc == 6 || argc == 7) && std::wcscmp(argv[1], L"--launch-standard") == 0) {
            ACCESS_MASK access = 0;
            if (argc >= 6) {
                if (std::wcscmp(argv[5], L"--edge-session") == 0) access = RecipeNamespace::recipe_access;
                else if (std::wcscmp(argv[5], L"--edge-session-with-subdirectories") == 0)
                    access = RecipeNamespace::with_subdirectory;
                else return 2;
            }
            const bool edge_owns_jobs = argc == 7 && std::wcscmp(argv[6], L"--edge-with-own-jobs") == 0;
            if (argc == 7 && !edge_owns_jobs) return 2;
            return launch_standard(argv[2], argv[3], argv[4], access, edge_owns_jobs);
        }
        if (argc == 2 && std::wcscmp(argv[1], L"--native-standard") == 0) {
            if (!_wfreopen(L"out\\native.log", L"wb", stderr)) return 3;
            token_environment("executing native recipe", GetCurrentProcess());
            require(ordinary_token(), "test process did not inherit an ordinary Windows token");
            const int result = run(false);
            if (!result) std::fputs("Native external dictation recipe passed.\n", stderr);
            return result;
        }
        if (argc == 1) return run(false);
        if (argc == 2 && std::wcscmp(argv[1], L"--clipboard") == 0) return run(true);
        return 2;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Native external target probe: %s\n", error.what());
        return 1;
    }
}
