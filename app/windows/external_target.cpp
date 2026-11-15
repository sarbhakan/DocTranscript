#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "external_target.h"

#include <ole2.h>
#include <uiautomationclient.h>

#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <deque>
#include <mutex>
#include <thread>
#include <utility>
#include <vector>
#ifdef NOTEVIVE_EXTERNAL_TEST_DIAGNOSTICS
#include <cstdio>
#endif

#include "notes.h"
#include "worker_protocol.h"

namespace doct::external {
namespace {

constexpr DWORD kMessageMs = 100, kProviderMs = 300, kReleaseMs = 400;
constexpr ULONGLONG kCaptureMs = 4000, kQueueMs = 2500;
constexpr ULONGLONG kIdleUiaPollMs = 250, kIdleUiaBudgetMs = 1000;
constexpr std::size_t kMaxSegment = 1024, kMaxQueued = 4;
constexpr DWORD kNoGui = GUI_INMOVESIZE | GUI_INMENUMODE | GUI_SYSTEMMENUMODE | GUI_POPUPMENUMODE;
// A closing UI never joins an external COM provider. Limit outstanding lanes
// even if a provider or a COM teardown overruns its configured timeout.
std::atomic<unsigned> lanes{0};

// The console recipe records only fixed guard labels and numeric status.
// No application, element, path, identifier, or transcription is logged.
inline bool veto(const char* guard, unsigned long status = 0) noexcept {
#ifdef NOTEVIVE_EXTERNAL_TEST_DIAGNOSTICS
    std::fprintf(stderr, "NoteVive external guard %s status=0x%08lx\n", guard, status);
#else
    (void)guard;
    (void)status;
#endif
    return false;
}
inline bool com_ok(const char* guard, HRESULT status) noexcept {
    return SUCCEEDED(status) || veto(guard, static_cast<unsigned long>(status));
}
#ifdef NOTEVIVE_EXTERNAL_TEST_DIAGNOSTICS
bool suppress_recipe_focus_events() noexcept {
    // Only the diagnostic fixture can reproduce a provider dropping focus events.
    static const bool suppress = [] {
        wchar_t value[2]{};
        return GetEnvironmentVariableW(L"NOTEVIVE_WPF_RECIPE_NO_FOCUS_EVENTS", value, 2) == 1 && value[0] == L'1';
    }();
    return suppress;
}
#endif
inline bool win32_veto(const char* guard) noexcept {
#ifdef NOTEVIVE_EXTERNAL_TEST_DIAGNOSTICS
    return veto(guard, GetLastError());
#else
    return veto(guard);
#endif
}
inline void editor_type_veto(CONTROLTYPEID type) noexcept {
#ifdef NOTEVIVE_EXTERNAL_TEST_DIAGNOSTICS
    switch (type) {
    case UIA_WindowControlTypeId: veto("uia.element_not_editor.window"); break;
    case UIA_PaneControlTypeId: veto("uia.element_not_editor.pane"); break;
    case UIA_CustomControlTypeId: veto("uia.element_not_editor.custom"); break;
    case UIA_TextControlTypeId: veto("uia.element_not_editor.text"); break;
    case UIA_GroupControlTypeId: veto("uia.element_not_editor.group"); break;
    default: veto("uia.element_not_editor.other"); break;
    }
#else
    (void)type;
#endif
}

struct Handle {
    HANDLE value = nullptr;
    ~Handle() { if (value) CloseHandle(value); }
    Handle() = default;
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
};

template<class T> struct ComPtr {
    T* value = nullptr;
    ~ComPtr() { if (value) value->Release(); }
    ComPtr() = default;
    ComPtr(const ComPtr&) = delete;
    ComPtr& operator=(const ComPtr&) = delete;
    T* operator->() const { return value; }
    T** out() { return &value; }
    explicit operator bool() const { return value != nullptr; }
};

struct Token {
    DWORD level = 0;
    bool elevated = false;
};
bool query_token(HANDLE process, Token& result) {
    Handle token;
    if (!OpenProcessToken(process, TOKEN_QUERY, &token.value)) return false;
    DWORD needed = 0;
    GetTokenInformation(token.value, TokenIntegrityLevel, nullptr, 0, &needed);
    if (!needed || needed > 4096) return false;
    // BYTE storage from the allocator has sufficient alignment for the label.
    std::vector<BYTE> storage(needed);
    if (!GetTokenInformation(token.value, TokenIntegrityLevel, storage.data(), needed, &needed)) return false;
    const auto sid = reinterpret_cast<TOKEN_MANDATORY_LABEL*>(storage.data())->Label.Sid;
    if (!IsValidSid(sid)) return false;
    const auto count = *GetSidSubAuthorityCount(sid);
    if (!count) return false;
    TOKEN_ELEVATION elevation{};
    if (!GetTokenInformation(token.value, TokenElevation, &elevation, sizeof(elevation), &needed)) return false;
    result = {*GetSidSubAuthority(sid, count - 1), elevation.TokenIsElevated != 0};
    return true;
}

struct Focus {
    HWND foreground = nullptr, field = nullptr;
    DWORD pid = 0, tid = 0;
};
bool focused(Focus& f) {
    const HWND foreground = GetForegroundWindow();
    if (!foreground) return veto("focus.foreground_missing");
    if (!IsWindowVisible(foreground) || !IsWindowEnabled(foreground)) return veto("focus.foreground_hidden_or_disabled");
    DWORD pid = 0, field_pid = 0;
    const DWORD tid = GetWindowThreadProcessId(foreground, &pid);
    GUITHREADINFO gui{};
    gui.cbSize = sizeof(gui);
    if (!tid || !pid) return veto("focus.foreground_owner");
    if (!GetGUIThreadInfo(tid, &gui)) return win32_veto("focus.thread_info");
    if (!gui.hwndFocus) return veto("focus.field_missing");
    if (gui.flags & kNoGui) return veto("focus.gui_mode", gui.flags & kNoGui);
    if (gui.hwndActive != foreground) return veto("focus.active_mismatch");
    if (GetAncestor(gui.hwndFocus, GA_ROOT) != foreground) return veto("focus.field_root_mismatch");
    if (GetWindowThreadProcessId(gui.hwndFocus, &field_pid) != tid || field_pid != pid)
        return veto("focus.field_owner_mismatch");
    if (!IsWindowVisible(gui.hwndFocus) || !IsWindowEnabled(gui.hwndFocus)) return veto("focus.field_hidden_or_disabled");
    if (GetForegroundWindow() != foreground) return veto("focus.foreground_changed");
    f = {foreground, gui.hwndFocus, pid, tid};
    return true;
}
bool stable(const Focus& f) {
    Focus now;
    return focused(now) && now.foreground == f.foreground && now.field == f.field &&
        now.pid == f.pid && now.tid == f.tid;
}
bool on_input_desktop() {
    auto input = OpenInputDesktop(0, FALSE, DESKTOP_READOBJECTS);
    if (!input) return win32_veto("desktop.input_open");
    auto thread = GetThreadDesktop(GetCurrentThreadId());
    wchar_t a[256]{}, b[256]{};
    DWORD needed = 0;
    const bool same = (thread || veto("desktop.thread_missing")) &&
        (GetUserObjectInformationW(input, UOI_NAME, a, sizeof(a), &needed) || win32_veto("desktop.input_query")) &&
        (GetUserObjectInformationW(thread, UOI_NAME, b, sizeof(b), &needed) || win32_veto("desktop.thread_query")) &&
        (std::wcscmp(a, b) == 0 || veto("desktop.not_input"));
    CloseDesktop(input);
    return same;
}
std::wstring program_label(HANDLE process) {
    std::array<wchar_t, 32768> path{};
    DWORD size = static_cast<DWORD>(path.size());
    if (!QueryFullProcessImageNameW(process, 0, path.data(), &size)) return {};
    std::wstring_view filename(path.data(), size);
    const auto slash = filename.find_last_of(L"\\/");
    filename.remove_prefix(slash == std::wstring_view::npos ? 0 : slash + 1);
    auto equal = [&](const wchar_t* name) { return CompareStringOrdinal(filename.data(),
        static_cast<int>(filename.size()), name, -1, TRUE) == CSTR_EQUAL; };
    if (equal(L"WINWORD.EXE")) return L"Word";
    if (equal(L"chrome.exe")) return L"Chrome";
    if (equal(L"msedge.exe")) return L"Edge";
    if (equal(L"firefox.exe")) return L"Firefox";
    if (equal(L"brave.exe")) return L"Brave";
    if (equal(L"vivaldi.exe")) return L"Vivaldi";
    if (equal(L"opera.exe")) return L"Opera";
    if (filename.empty() || filename.size() > 64 || !wire::valid_text(filename)) return {};
    return std::wstring(filename);
}
bool native_edit(HWND hwnd) {
    wchar_t name[32]{};
    return RealGetWindowClassW(hwnd, name, 32) && CompareStringOrdinal(name, -1, L"EDIT", -1, TRUE) == CSTR_EQUAL;
}
bool message_to(HWND hwnd, UINT message_id, WPARAM wparam, LPARAM lparam, DWORD_PTR& result) {
    result = 0;
    return SendMessageTimeoutW(hwnd, message_id, wparam, lparam,
                              SMTO_ABORTIFHUNG | SMTO_BLOCK | SMTO_ERRORONEXIT, kMessageMs, &result) != 0;
}
struct Caret {
    DWORD offset = 0;
    DWORD_PTR size = 0, limit = 0;
};
Result edit_caret(HWND edit, Caret& caret) {
    SetLastError(0);
    const auto style = GetWindowLongPtrW(edit, GWL_STYLE);
    if ((!style && GetLastError()) || !IsWindowUnicode(edit) ||
        (style & (ES_READONLY | ES_PASSWORD | ES_NUMBER | ES_UPPERCASE | ES_LOWERCASE))) return Result::protected_field;
    DWORD_PTR password = 0, ignored = 0;
    if (!message_to(edit, EM_GETPASSWORDCHAR, 0, 0, password)) return Result::unsupported;
    if (password) return Result::protected_field;
    DWORD first = MAXDWORD, last = MAXDWORD;
    if (!message_to(edit, EM_GETSEL, reinterpret_cast<WPARAM>(&first),
                    reinterpret_cast<LPARAM>(&last), ignored) ||
        !message_to(edit, WM_GETTEXTLENGTH, 0, 0, caret.size) ||
        !message_to(edit, EM_GETLIMITTEXT, 0, 0, caret.limit) ||
        first == MAXDWORD || first != last || last > caret.size || caret.size > caret.limit) return Result::unsupported;
    caret.offset = first;
    return Result::ready;
}

bool property_bool(IUIAutomationElement* element, PROPERTYID id, bool expected) {
    VARIANT value{};
    const HRESULT hr = element->GetCurrentPropertyValueEx(id, TRUE, &value);
    const bool matches = SUCCEEDED(hr) && value.vt == VT_BOOL &&
        value.boolVal == (expected ? VARIANT_TRUE : VARIANT_FALSE);
    VariantClear(&value);
    return matches;
}
bool non_password(IUIAutomationElement* element, CONTROLTYPEID type) {
    VARIANT password{};
    const HRESULT hr = element->GetCurrentPropertyValueEx(UIA_IsPasswordPropertyId, TRUE, &password);
    const bool explicit_value = SUCCEEDED(hr) && password.vt == VT_BOOL;
    const bool allowed = explicit_value && password.boolVal == VARIANT_FALSE;
    VariantClear(&password);
    if (explicit_value || type != UIA_DocumentControlTypeId || FAILED(hr)) {
        if (allowed) return true;
        return veto(explicit_value ? "uia.password_flag_true" : "uia.password_flag_unverified",
                    static_cast<unsigned long>(hr));
    }
    // Document providers need not implement edit-specific IsPassword.
    // Require a recognised MSAA state via UIA when that flag is absent.
    VARIANT state{};
    const HRESULT state_hr = element->GetCurrentPropertyValueEx(UIA_LegacyIAccessibleStatePropertyId, TRUE, &state);
    const bool legacy_allowed = SUCCEEDED(state_hr) && state.vt == VT_I4 &&
        !(state.lVal & (STATE_SYSTEM_PROTECTED | STATE_SYSTEM_READONLY | STATE_SYSTEM_UNAVAILABLE));
    VariantClear(&state);
    return legacy_allowed || veto("uia.legacy_password_state_unverified", static_cast<unsigned long>(state_hr));
}
bool runtime_id(IUIAutomationElement* element, std::vector<LONG>& id) {
    SAFEARRAY* array = nullptr;
    const HRESULT hr = element->GetRuntimeId(&array);
    if (!array) return veto("uia.runtime_id_missing", static_cast<unsigned long>(hr));
    LONG lo = 0, hi = 0;
    LONG* data = nullptr;
    const bool valid = com_ok("uia.runtime_id_query", hr) &&
        (SafeArrayGetDim(array) == 1 || veto("uia.runtime_id_dimension")) &&
        (SafeArrayGetElemsize(array) == sizeof(LONG) || veto("uia.runtime_id_element_size")) &&
        com_ok("uia.runtime_id_lower_bound", SafeArrayGetLBound(array, 1, &lo)) &&
        com_ok("uia.runtime_id_upper_bound", SafeArrayGetUBound(array, 1, &hi)) &&
        ((hi >= lo && static_cast<std::int64_t>(hi) - lo < 64) || veto("uia.runtime_id_bounds")) &&
        com_ok("uia.runtime_id_array_access", SafeArrayAccessData(array, reinterpret_cast<void**>(&data)));
    if (valid) {
        id.assign(data, data + (hi - lo + 1));
        SafeArrayUnaccessData(array);
    }
    SafeArrayDestroy(array);
    return valid;
}
bool writable_caret(IUIAutomationElement* element) {
    // No Value/Text is fetched: both APIs below return only editability and
    // range endpoints. Refuse if the provider cannot rule out a selection.
    if (property_bool(element, UIA_ValueIsReadOnlyPropertyId, true)) return veto("uia.value_read_only");
    ComPtr<IUIAutomationTextPattern> text;
    if (!com_ok("uia.text_pattern_query", element->GetCurrentPatternAs(UIA_TextPatternId,
                __uuidof(IUIAutomationTextPattern), reinterpret_cast<void**>(text.out())))) return false;
    if (!text) return veto("uia.text_pattern_missing");
    ComPtr<IUIAutomationTextRangeArray> ranges;
    if (!com_ok("uia.selection_query", text->GetSelection(ranges.out()))) return false;
    if (!ranges) return veto("uia.selection_missing");
    int length = 0, compare = 0;
    ComPtr<IUIAutomationTextRange> range;
    if (!com_ok("uia.selection_length_query", ranges->get_Length(&length))) return false;
    if (length != 1) return veto("uia.selection_not_single");
    if (!com_ok("uia.selection_range_query", ranges->GetElement(0, range.out()))) return false;
    if (!range) return veto("uia.selection_range_missing");
    if (!com_ok("uia.selection_endpoint_query", range->CompareEndpoints(TextPatternRangeEndpoint_Start, range.value,
                                                                       TextPatternRangeEndpoint_End, &compare))) return false;
    if (compare != 0) return veto("uia.selection_not_collapsed");
    VARIANT read_only{};
    const HRESULT hr = range->GetAttributeValue(UIA_IsReadOnlyAttributeId, &read_only);
    // Accept only a definite Boolean, never a mixed/unsupported value.
    const bool writeable = SUCCEEDED(hr) && read_only.vt == VT_BOOL && read_only.boolVal == VARIANT_FALSE;
    if (!writeable) {
        if (FAILED(hr)) veto("uia.read_only_attribute_query", static_cast<unsigned long>(hr));
        else if (read_only.vt != VT_BOOL) veto("uia.read_only_attribute_not_bool");
        else veto("uia.read_only_attribute_not_false");
    }
    VariantClear(&read_only);
    return writeable;
}
bool within_document(IUIAutomation2* uia, IUIAutomationElement* field, HWND foreground) {
    ComPtr<IUIAutomationTreeWalker> walker;
    if (FAILED(uia->get_RawViewWalker(walker.out())) || !walker) return false;
    field->AddRef();
    ComPtr<IUIAutomationElement> entry;
    entry.value = field;
    for (unsigned i = 0; i < 32; ++i) {
        ComPtr<IUIAutomationElement> parent;
        if (FAILED(walker->GetParentElement(entry.value, parent.out())) || !parent) return false;
        CONTROLTYPEID type = 0;
        UIA_HWND hwnd = nullptr;
        if (FAILED(parent->get_CurrentControlType(&type)) ||
            FAILED(parent->get_CurrentNativeWindowHandle(&hwnd))) return false;
        if (type == UIA_DocumentControlTypeId) return true;
        if (hwnd == foreground || type == UIA_WindowControlTypeId) return false;
        std::swap(entry.value, parent.value);
    }
    return false;
}
Result inspect_uia(IUIAutomation2* uia, const Focus& f, bool browser, std::vector<LONG>& id) {
    ComPtr<IUIAutomationElement> element;
    if (!com_ok("uia.focused_element_query", uia->GetFocusedElement(element.out()))) return Result::unsupported;
    if (!element) { veto("uia.focused_element_missing"); return Result::unsupported; }
    int pid = 0;
    CONTROLTYPEID type = 0;
    BOOL enabled = FALSE, has_focus = FALSE;
    if (!com_ok("uia.element_process_query", element->get_CurrentProcessId(&pid))) return Result::unsupported;
    if (static_cast<DWORD>(pid) != f.pid) { veto("uia.element_process_mismatch"); return Result::unsupported; }
    if (!com_ok("uia.element_control_type_query", element->get_CurrentControlType(&type))) return Result::unsupported;
    if (type != UIA_EditControlTypeId && type != UIA_DocumentControlTypeId) {
        editor_type_veto(type);
        return Result::unsupported;
    }
    if (!com_ok("uia.element_enabled_query", element->get_CurrentIsEnabled(&enabled))) return Result::unsupported;
    if (!enabled) { veto("uia.element_disabled"); return Result::unsupported; }
    if (!com_ok("uia.element_has_focus_query", element->get_CurrentHasKeyboardFocus(&has_focus))) return Result::unsupported;
    if (!has_focus) { veto("uia.element_has_no_keyboard_focus"); return Result::unsupported; }
    if (!non_password(element.value, type)) return Result::protected_field;
    if (browser && type == UIA_EditControlTypeId && !within_document(uia, element.value, f.foreground)) {
        veto("uia.browser_editor_outside_document");
        return Result::unsupported;
    }
    return runtime_id(element.value, id) && writable_caret(element.value) ? Result::ready : Result::unsupported;
}

bool same_uia_target(IUIAutomation2* uia, const std::vector<LONG>& id) {
    // Read focus again after provider checks, which may require several
    // inter-process calls. Never retain/restore the provider's input focus.
    ComPtr<IUIAutomationElement> current;
    std::vector<LONG> current_id;
    return SUCCEEDED(uia->GetFocusedElement(current.out())) && current &&
        runtime_id(current.value, current_id) && current_id == id;
}

class FocusEvents final : public IUIAutomationFocusChangedEventHandler {
public:
    std::atomic<unsigned long> epoch{0};
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** result) override {
        if (!result) return E_POINTER;
        *result = nullptr;
        if (!IsEqualIID(iid, __uuidof(IUnknown)) &&
            !IsEqualIID(iid, __uuidof(IUIAutomationFocusChangedEventHandler))) return E_NOINTERFACE;
        *result = static_cast<IUIAutomationFocusChangedEventHandler*>(this);
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs_; }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG count = --refs_;
        if (!count) delete this;
        return count;
    }
    HRESULT STDMETHODCALLTYPE HandleFocusChangedEvent(IUIAutomationElement*) override {
#ifdef NOTEVIVE_EXTERNAL_TEST_DIAGNOSTICS
        if (suppress_recipe_focus_events()) return S_OK;
#endif
        // A provider callback needn't complete a COM request or share a UI
        // lock. A queued change invalidates the session even if focus returns.
        ++epoch;
        return S_OK;
    }

private:
    std::atomic<ULONG> refs_{1};
};

struct UiaSession {
    HRESULT apartment = E_FAIL;
    IUIAutomation2* uia = nullptr;
    FocusEvents* events = nullptr;
    bool listening = false;
    bool start() {
        apartment = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        if (!com_ok("uia.com_initialization", apartment)) return false;
        if (!com_ok("uia.com_creation", CoCreateInstance(__uuidof(CUIAutomation8), nullptr, CLSCTX_INPROC_SERVER,
                        __uuidof(IUIAutomation2), reinterpret_cast<void**>(&uia)))) return false;
        if (!uia) return veto("uia.com_interface_missing");
        if (!com_ok("uia.connection_timeout_setting", uia->put_ConnectionTimeout(kProviderMs)) ||
            !com_ok("uia.transaction_timeout_setting", uia->put_TransactionTimeout(kProviderMs)) ||
            !com_ok("uia.auto_focus_setting", uia->put_AutoSetFocus(FALSE))) return false;
        events = new FocusEvents;
        listening = com_ok("uia.focus_event_subscription", uia->AddFocusChangedEventHandler(nullptr, events));
        return listening;
    }
    ~UiaSession() {
        if (listening) uia->RemoveFocusChangedEventHandler(events);
        if (events) events->Release();
        if (uia) uia->Release();
        if (SUCCEEDED(apartment)) CoUninitialize();
    }
};

bool modifiers_down() {
    for (auto key : {VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN, VK_SPACE}) {
        if (GetAsyncKeyState(key) & 0x8000) return true;
    }
    return false;
}

std::wstring external_line(std::wstring_view raw, bool append_space) {
    constexpr std::wstring_view gaps = L" \t\r\n\u2028\u2029";
    const auto first = raw.find_first_not_of(gaps);
    if (first == std::wstring_view::npos) return {};
    raw = raw.substr(first, raw.find_last_not_of(gaps) - first + 1);
    std::wstring line;
    line.reserve(raw.size() + (append_space ? 1u : 0u));
    if (append_space) line.push_back(L' ');
    bool break_pending = false;
    for (wchar_t ch : raw) {
        if (ch == L'\r' || ch == L'\n' || ch == L'\t' || ch == L'\u2028' || ch == L'\u2029') {
            break_pending = true;
            continue;
        }
        if (break_pending && ch != L' ' && !line.empty() && line.back() != L' ') line.push_back(L' ');
        break_pending = false;
        line.push_back(ch);
    }
    return line;
}

std::vector<INPUT> make_inputs(std::wstring_view line) {
    std::vector<INPUT> keys;
    keys.reserve(line.size() * 2);
    for (wchar_t unit : line) {
        INPUT event{};
        event.type = INPUT_KEYBOARD;
        event.ki.wScan = static_cast<WORD>(unit);
        event.ki.dwFlags = KEYEVENTF_UNICODE;
        keys.push_back(event);
        event.ki.dwFlags |= KEYEVENTF_KEYUP;
        keys.push_back(event);
    }
    return keys;
}

struct ClipboardBlock {
    HGLOBAL handle;
    explicit ClipboardBlock(SIZE_T bytes) : handle(GlobalAlloc(GMEM_MOVEABLE, bytes)) {}
    ~ClipboardBlock() { if (handle) GlobalFree(handle); }
    bool fill(const void* source, const SIZE_T bytes) const {
        void* data = GlobalLock(handle);
        if (!data) return false;
        std::memcpy(data, source, bytes);
        GlobalUnlock(handle);
        return true;
    }
    bool offer(UINT format) {
        if (!SetClipboardData(format, handle)) return false;
        handle = nullptr;
        return true;
    }
};

} // namespace

struct Target::State {
    explicit State(Focus focus) : target(focus), captured_at(GetTickCount64()), is_edit(native_edit(focus.field)) {}
    struct Segment { std::wstring text; ULONGLONG queued_at; };

    const Focus target;
    const ULONGLONG captured_at;
    const bool is_edit;
    std::atomic<bool> cancelled{false};
    std::mutex mutex;
    std::condition_variable wake;
    Result result = Result::pending;
    bool in_flight = true;
    ULONGLONG send_by = 0; // Protected by mutex.
    std::deque<Segment> queue;
    std::wstring label;
    Handle process;
    Caret caret;
    bool wrote = false, browser = false;

    void fail(Result why) {
        {
            std::lock_guard lock(mutex);
            if (cancelled.exchange(true)) return;
            result = why;
            in_flight = false;
            queue.clear();
        }
        wake.notify_all();
    }
    bool still_target(ULONGLONG deadline) const {
        if (cancelled || GetTickCount64() > deadline || !on_input_desktop() ||
            WaitForSingleObject(process.value, 0) != WAIT_TIMEOUT || !stable(target)) return false;
        return !cancelled;
    }
    Result send_edit(std::wstring_view line, ULONGLONG deadline) {
        Caret current;
        if (!native_edit(target.field)) return Result::target_changed;
        auto status = edit_caret(target.field, current);
        if (status != Result::ready) return status;
        if (current.offset != caret.offset || current.size != caret.size) return Result::target_changed;
        if (line.size() > current.limit - current.size) return Result::unsupported;
        if (!still_target(deadline)) return Result::target_changed;
        // This is a marshalled system message below WM_USER to one HWND, not
        // simulated foreground keys. EM_REPLACESEL itself provides no receipt.
        DWORD_PTR ignored = 0;
        if (!message_to(target.field, EM_REPLACESEL, TRUE, reinterpret_cast<LPARAM>(line.data()), ignored))
            return Result::delivery_uncertain;
        status = edit_caret(target.field, caret);
        if (status != Result::ready || caret.size != current.size + line.size() ||
            caret.offset != current.offset + line.size()) return Result::delivery_uncertain;
        return Result::inserted;
    }
    Result send_uia(UiaSession& uia, const std::vector<LONG>& captured_id, unsigned long epoch,
                    std::wstring_view line, ULONGLONG deadline) {
        // Wait briefly only on this lane. Never synthesize a modifier release.
        const ULONGLONG release_by = GetTickCount64() + kReleaseMs;
        while (modifiers_down()) {
            if (GetTickCount64() > release_by) return Result::unsupported;
            if (!still_target(deadline) || uia.events->epoch != epoch) return Result::target_changed;
            Sleep(10);
        }
        auto keys = make_inputs(line);
        std::vector<LONG> current_id;
        const auto status = inspect_uia(uia.uia, target, browser, current_id);
        if (status != Result::ready) return status;
        if (current_id != captured_id || !same_uia_target(uia.uia, captured_id) ||
            !still_target(deadline) || uia.events->epoch != epoch)
            return Result::target_changed;
        if (modifiers_down()) return Result::unsupported;
        // Windows does not accept a destination for SendInput. This final check
        // narrows, but cannot eliminate, the race with later focus changes.
        const auto sent = SendInput(static_cast<UINT>(keys.size()), keys.data(), sizeof(INPUT));
        return sent == keys.size() ? Result::submitted : Result::delivery_uncertain;
    }
    void run() {
        UiaSession uia;
        std::vector<LONG> id;
        unsigned long epoch = 0;
        process.value = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, target.pid);
        Token self, foreign;
        if (!process.value || !query_token(GetCurrentProcess(), self) || !query_token(process.value, foreign) ||
            foreign.elevated || foreign.level >= SECURITY_MANDATORY_HIGH_RID || foreign.level != self.level)
            return fail(Result::protected_field);
        const auto capture_deadline = captured_at + kCaptureMs;
        if (!still_target(capture_deadline)) return fail(Result::target_changed);
        auto name = program_label(process.value);
        browser = name == L"Chrome" || name == L"Edge" || name == L"Firefox" ||
            name == L"Brave" || name == L"Vivaldi" || name == L"Opera";
        Result initial;
        if (is_edit) {
            if (browser) return fail(Result::unsupported);
            initial = edit_caret(target.field, caret);
        } else {
            if (!uia.start()) return fail(Result::unsupported);
            epoch = uia.events->epoch.load();
            initial = inspect_uia(uia.uia, target, browser, id);
        }
        if (initial != Result::ready) return fail(initial);
        if (!still_target(capture_deadline) || (!is_edit && uia.events->epoch != epoch))
            return fail(Result::target_changed);
        {
            std::lock_guard lock(mutex);
            if (cancelled) return;
            label = std::move(name);
            result = Result::ready;
            in_flight = false;
        }
        ULONGLONG next_uia_identity_check = GetTickCount64() + kIdleUiaPollMs;
        for (;;) {
            Segment segment;
            bool verify_idle_uia = false;
            {
                std::unique_lock lock(mutex);
                // Even with no text queued, invalidate a DOM focus change
                // observed by the UI Automation provider.
                wake.wait_for(lock, std::chrono::milliseconds(50), [&] { return cancelled || !queue.empty(); });
                if (cancelled) return;
                if (!is_edit && uia.events->epoch != epoch) {
                    lock.unlock();
                    return fail(Result::target_changed);
                }
                if (queue.empty()) {
                    if (is_edit || GetTickCount64() < next_uia_identity_check) continue;
                    verify_idle_uia = true;
                } else {
                    segment = std::move(queue.front());
                    queue.pop_front();
                    in_flight = true;
                    send_by = segment.queued_at + kQueueMs;
                    result = Result::queued;
                }
            }
            if (verify_idle_uia) {
                // Several windowless controls can share one HWND. Providers
                // need not deliver a timely focus event for a change between them.
                // On the existing worker, read only the focused RuntimeId;
                // don't pause UI, hold the queue lock, or read the field value.
                const auto deadline = GetTickCount64() + kIdleUiaBudgetMs;
                if (!still_target(deadline)) return fail(Result::target_changed);
                if (!same_uia_target(uia.uia, id)) {
                    veto("uia.idle_identity_lost");
                    return fail(Result::target_changed);
                }
                if (!still_target(deadline) || uia.events->epoch != epoch) return fail(Result::target_changed);
                next_uia_identity_check = GetTickCount64() + kIdleUiaPollMs;
                continue;
            }
            const auto deadline = segment.queued_at + kQueueMs;
            const auto line = external_line(segment.text, wrote);
            if (!still_target(deadline)) return fail(Result::target_changed);
            const auto outcome = is_edit ? send_edit(line, deadline) : send_uia(uia, id, epoch, line, deadline);
            if (outcome != Result::inserted && outcome != Result::submitted) return fail(outcome);
            wrote = true;
            next_uia_identity_check = GetTickCount64() + kIdleUiaPollMs;
            {
                std::lock_guard lock(mutex);
                if (cancelled) return;
                result = queue.empty() ? outcome : Result::queued;
                in_flight = false;
                send_by = 0;
            }
        }
    }
};

thread_local Target* Target::monitoring_ = nullptr;

Target::Target() = default;
Target::~Target() { reset(); }

void CALLBACK Target::on_event(HWINEVENTHOOK hook, DWORD event, HWND window,
                               LONG id_object, LONG id_child, DWORD tid, DWORD event_time) {
#ifdef NOTEVIVE_EXTERNAL_TEST_DIAGNOSTICS
    if (suppress_recipe_focus_events()) return;
#endif
    auto* self = monitoring_;
    if (!self || !self->state_ || (hook != self->foreground_hook_ && hook != self->focus_hook_)) return;
    const auto& state = *self->state_;
    const auto since_capture = event_time - static_cast<DWORD>(state.captured_at);
    if (since_capture > 0x7fffffffu) return; // Older queued notification, including tick wrap.
    if (event == EVENT_SYSTEM_FOREGROUND && window != state.target.foreground) {
        self->state_->fail(Result::target_changed);
    } else if (event == EVENT_OBJECT_FOCUS) {
        // MSAA may report invisible/windowless controls under the same HWND.
        // Do not ignore a focus event in the selected GUI thread just because
        // its HWND was unchanged. Unrelated background events are ignored.
        const bool in_target_thread = tid == state.target.tid ||
            (window && GetWindowThreadProcessId(window, nullptr) == state.target.tid);
        if (!stable(state.target) || (in_target_thread && (window != state.target.field ||
                (!state.is_edit && (id_object != OBJID_WINDOW || id_child != CHILDID_SELF)))))
            self->state_->fail(Result::target_changed);
    }
}

Result Target::capture(HWND owner, HWND expected_foreground, DWORD expected_pid) {
    reset();
    Focus focus;
    if (!owner || monitoring_) { veto("capture.owner_or_monitor"); return Result::unsupported; }
    if (!on_input_desktop() || !focused(focus)) return Result::unsupported;
    if (focus.pid == GetCurrentProcessId() || focus.foreground == owner) {
        veto("capture.own_window"); return Result::unsupported;
    }
    if ((expected_foreground && focus.foreground != expected_foreground) ||
        (expected_pid && focus.pid != expected_pid)) {
        veto("capture.expected_target_mismatch"); return Result::unsupported;
    }
    std::shared_ptr<State> state;
    try { state = std::make_shared<State>(focus); }
    catch (...) { veto("capture.state_creation"); return Result::unsupported; }
    state_ = state;
    monitoring_ = this;
    foreground_hook_ = SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, nullptr,
                                        on_event, 0, 0, WINEVENT_OUTOFCONTEXT);
    focus_hook_ = SetWinEventHook(EVENT_OBJECT_FOCUS, EVENT_OBJECT_FOCUS, nullptr,
                                   on_event, 0, 0, WINEVENT_OUTOFCONTEXT);
    if (!foreground_hook_ || !focus_hook_ || !stable(focus)) {
        veto(!foreground_hook_ ? "capture.foreground_hook" : !focus_hook_ ? "capture.focus_hook" : "capture.focus_not_stable");
        reset();
        return Result::unsupported;
    }
    if (lanes.fetch_add(1) != 0) {
        veto("capture.worker_busy");
        --lanes;
        reset();
        return Result::unsupported;
    }
    try {
        std::thread([state] {
            try { state->run(); }
            catch (...) { veto("capture.worker_exception"); state->fail(Result::unsupported); }
            --lanes;
        }).detach();
    } catch (...) {
        veto("capture.worker_creation");
        --lanes;
        reset();
        return Result::unsupported;
    }
    return Result::pending;
}

Result Target::check() {
    if (!state_) return Result::inactive;
    if (!state_->cancelled) {
        if (!stable(state_->target)) state_->fail(Result::target_changed);
        else {
            const auto now = GetTickCount64();
            Result overdue = Result::inactive;
            {
                std::lock_guard lock(state_->mutex);
                if (state_->result == Result::pending && now > state_->captured_at + kCaptureMs)
                    overdue = Result::unsupported;
                else if ((state_->send_by && now > state_->send_by) || (!state_->queue.empty() &&
                         now > state_->queue.front().queued_at + kQueueMs))
                    overdue = Result::delivery_uncertain;
            }
            if (overdue != Result::inactive) {
                if (overdue == Result::unsupported) veto("capture.deadline");
                state_->fail(overdue);
            }
        }
    }
    std::lock_guard lock(state_->mutex);
    return state_->result;
}

Result Target::forward(std::wstring_view final) {
    auto status = check();
    if (status != Result::pending && status != Result::ready && status != Result::queued &&
        status != Result::inserted && status != Result::submitted) return status;
    if (final.empty() || final.find_first_not_of(L" \t\r\n\u2028\u2029") == std::wstring_view::npos)
        return Result::no_text;
    if (final.size() > kMaxSegment || !wire::valid_text(final)) {
        state_->fail(Result::invalid_text);
        return Result::invalid_text;
    }
    {
        std::lock_guard lock(state_->mutex);
        if (state_->cancelled) return state_->result;
        if (state_->queue.size() < kMaxQueued) {
            state_->queue.push_back({std::wstring(final), GetTickCount64()});
            if (state_->result != Result::pending) state_->result = Result::queued;
            state_->wake.notify_one();
            return Result::queued;
        }
    }
    state_->fail(Result::unsupported);
    return Result::unsupported;
}

bool Target::busy() const {
    if (!state_) return false;
    std::lock_guard lock(state_->mutex);
    return !state_->cancelled && (state_->in_flight || !state_->queue.empty());
}

std::wstring Target::destination_label() const {
    if (!state_) return {};
    std::lock_guard lock(state_->mutex);
    return state_->label;
}

void Target::reset() {
    if (state_) state_->fail(Result::inactive);
    if (foreground_hook_) UnhookWinEvent(foreground_hook_);
    if (focus_hook_) UnhookWinEvent(focus_hook_);
    foreground_hook_ = focus_hook_ = nullptr;
    if (monitoring_ == this) monitoring_ = nullptr;
    state_.reset();
}

const wchar_t* message(Result result) {
    switch (result) {
    case Result::inactive: return L"Destination externe désactivée.";
    case Result::pending: return L"Vérification du champ actif…";
    case Result::ready: return L"Champ actif prêt.";
    case Result::queued: return L"Envoi du segment vers le champ actif…";
    case Result::inserted: return L"Segment inséré dans le champ actif.";
    case Result::submitted: return L"Segment envoyé. Vérifiez le texte dans le champ de destination.";
    case Result::no_text: return L"Aucun texte confirmé à envoyer.";
    case Result::unsupported: return L"Champ non compatible ou indisponible. La dictée reste dans NoteVive.";
    case Result::protected_field: return L"Champ protégé ou application à accès restreint. La dictée reste dans NoteVive.";
    case Result::target_changed: return L"Le champ actif a changé. L’envoi s’arrête ; la dictée reste dans NoteVive.";
    case Result::delivery_uncertain: return L"Envoi non confirmé. Vérifiez le champ de destination avant de coller la note.";
    case Result::invalid_text: return L"Segment non transmissible. La dictée reste dans NoteVive.";
    }
    return L"Destination externe désactivée.";
}

bool copy_note_text(HWND owner, std::wstring_view text) {
    if (!owner || !IsWindow(owner) || text.empty() || text.size() > notes::kMaxText || !wire::valid_text(text))
        return false;
    const std::wstring terminated(text);
    const SIZE_T size = (terminated.size() + 1) * sizeof(wchar_t);
    const auto format = RegisterClipboardFormatW(L"ExcludeClipboardContentFromMonitorProcessing");
    if (!format) return false;
    const DWORD marker = 0;
    ClipboardBlock exclusion(sizeof(marker)), payload(size);
    if (!exclusion.fill(&marker, sizeof(marker)) || !payload.fill(terminated.c_str(), size) ||
        !OpenClipboard(owner)) return false;
    // Exclude from the built-in Windows history/sync before offering note
    // text. Clipboard remains available to local apps after explicit copy.
    const bool copied = EmptyClipboard() && exclusion.offer(format) && payload.offer(CF_UNICODETEXT);
    CloseClipboard();
    return copied;
}

} // namespace doct::external
