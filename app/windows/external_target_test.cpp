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
#include <sddl.h>
#include <userenv.h>

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

bool hosted_recipe() {
    const auto expected = [](const wchar_t* name, const wchar_t* value) {
        wchar_t buffer[32]{};
        const DWORD size = GetEnvironmentVariableW(name, buffer, 32);
        return size && size < 32 && std::wcscmp(buffer, value) == 0;
    };
    return expected(L"GITHUB_ACTIONS", L"true") && expected(L"RUNNER_ENVIRONMENT", L"github-hosted");
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
    static void log_label(HANDLE object, const char* name) {
        SECURITY_INFORMATION security = LABEL_SECURITY_INFORMATION;
        DWORD needed = 0;
        GetUserObjectSecurity(object, &security, nullptr, 0, &needed);
        std::vector<BYTE> descriptor(needed && needed <= 65536 ? needed : 0);
        if (descriptor.empty() ||
            !GetUserObjectSecurity(object, &security, descriptor.data(), needed, &needed)) {
            std::fprintf(stderr, "%s integrity label unreadable (%lu)\n", name,
                         static_cast<unsigned long>(GetLastError()));
            return;
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
                    std::fprintf(stderr, "%s integrity=0x%04lx mandatory_policy=0x%lx\n", name,
                        static_cast<unsigned long>(*GetSidSubAuthority(sid, *GetSidSubAuthorityCount(sid) - 1)),
                        static_cast<unsigned long>(label->Mask));
                    return;
                }
            }
        }
        std::fprintf(stderr, "%s has no explicit integrity label\n", name);
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
    bool start(HANDLE token, PSID account) {
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
            sid_text + L")S:(ML;;NW;;;ME)";
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
        log_label(temporary, "Recipe desktop");
        const DWORD desktop_check = access_with(thread_token.value, station_name, name.c_str());
        std::fprintf(stderr, "Recipe account desktop full access: %lu\n", static_cast<unsigned long>(desktop_check));
        if (desktop_check) { SetLastError(desktop_check); return false; }
        path = std::wstring(station_name) + L"\\" + name;
        if (!SwitchDesktop(temporary)) return false;
        switched = true;
        std::fputs("Using temporary medium-integrity input desktop. Default was not modified.\n", stderr);
        return true;
    }
};

struct RecipeAccount {
    std::wstring name;
    std::wstring sid_string;
    std::vector<BYTE> sid_storage;
    wchar_t password[41]{};
    LocalHandle token;
    bool created = false, launch_succeeded = false;

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
        if (launch_succeeded && !sid_string.empty()) {
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

int launch_standard(const wchar_t* executable, const wchar_t* arguments, const wchar_t* directory) {
    if (!hosted_recipe()) {
        std::fputs("Temporary local accounts are only used on hosted GitHub Actions.\n", stderr);
        return 1;
    }
    if (!stage_directory(directory)) {
        std::fputs("The standard recipe needs a fresh private staging directory.\n", stderr);
        return 1;
    }
    // Declare cleanup in reverse order: stop processes, restore desktop ACLs,
    // then remove the isolated profile and account.
    RecipeAccount account;
    RecipeDesktop desktop;
    LocalHandle job;
    const auto failure = [](const char* operation) {
        const auto error = GetLastError();
        std::fprintf(stderr, "%s failed (Windows error %lu)\n", operation, static_cast<unsigned long>(error));
        return 1;
    };
    if (!account.start()) return failure("Create and verify local standard test account");
    const std::wstring output = std::wstring(directory) + L"\\out";
    if (!grant_stage_access(directory, account.sid(), false) || !grant_stage_access(output.c_str(), account.sid(), true))
        return failure("Grant access to isolated test files");

    job.value = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!job.value || !SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
        return failure("SetInformationJobObject");
    if (!desktop.start(account.token.value, account.sid())) return failure("Prepare temporary Windows input desktop");
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
    LocalHandle child_process{child.hProcess}, child_thread{child.hThread};
    if (!AssignProcessToJobObject(job.value, child_process.value)) {
        const auto code = failure("AssignProcessToJobObject");
        TerminateProcess(child_process.value, 1);
        return code;
    }
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
    TerminateJobObject(job.value, 1); // No browser/fixture descendants on the retired desktop.
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
        if (argc == 5 && std::wcscmp(argv[1], L"--launch-standard") == 0)
            return launch_standard(argv[2], argv[3], argv[4]);
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
