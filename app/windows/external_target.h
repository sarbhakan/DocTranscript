#pragma once

#include <windows.h>

#include <memory>
#include <string>
#include <string_view>

namespace doct::external {

enum class Result {
    inactive, pending, ready, queued, inserted, submitted, no_text,
    unsupported, protected_field, target_changed, delivery_uncertain, invalid_text,
};

// One target per UI thread. Capture while the external window still has focus.
// After a successful local save, queue each final segment once. check() may
// be called by the UI timer; a normal stop may wait for busy() to become false.
// A lock, cancellation or exit must call reset() instead of waiting.
class Target {
public:
    Target();
    ~Target();
    Target(const Target&) = delete;
    Target& operator=(const Target&) = delete;

    Result capture(HWND owner, HWND expected_foreground = nullptr, DWORD expected_pid = 0);
    Result check();
    Result forward(std::wstring_view final);
    bool busy() const;
    std::wstring destination_label() const;
    void reset();

private:
    struct State;
    std::shared_ptr<State> state_;
    HWINEVENTHOOK foreground_hook_ = nullptr, focus_hook_ = nullptr;
    static thread_local Target* monitoring_;
    static void CALLBACK on_event(HWINEVENTHOOK, DWORD, HWND, LONG, LONG, DWORD, DWORD);
};

const wchar_t* message(Result result);
bool copy_note_text(HWND owner, std::wstring_view text);

} // namespace doct::external
