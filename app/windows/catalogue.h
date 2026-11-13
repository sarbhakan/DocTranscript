#pragma once
#include <windows.h>
#include <string>

namespace doct {
// Standalone, read-only lookup. Never receives the active note or a patient identifier.
void show_catalogue(HWND parent, const std::wstring& runtime_directory);
}
