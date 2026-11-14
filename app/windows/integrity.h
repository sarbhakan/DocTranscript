#pragma once
#include <string>

namespace doct {
bool verify_engine_files(const std::wstring& runtime_directory) noexcept;
bool verify_worker_file(const std::wstring& runtime_directory) noexcept;
bool verify_catalogue_file(const std::wstring& runtime_directory) noexcept;
}
