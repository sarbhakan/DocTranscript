// Minimal process initialisation fixture for the hosted Windows external
// dictation recipe. No COM, microphone, clipboard or browser.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

int main() {
    constexpr char startup[] = "User32 fixture reached main\r\n";
    const HANDLE output = CreateFileW(L"out\\user32.log", GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                                      CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (output == INVALID_HANDLE_VALUE) return 4;
    DWORD size = 0;
    if (!WriteFile(output, startup, sizeof(startup) - 1, &size, nullptr)) return 1;
    HWND window = CreateWindowExW(0, L"STATIC", L"NoteVive test window", WS_POPUP,
                                  0, 0, 100, 50, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
    if (!window) return 2;
    DestroyWindow(window);
    constexpr char created[] = "User32 fixture created a window\r\n";
    const bool written = WriteFile(output, created, sizeof(created) - 1, &size, nullptr) != FALSE;
    CloseHandle(output);
    return written ? 0 : 3;
}
