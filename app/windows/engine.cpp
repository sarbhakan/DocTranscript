#include "engine.h"
#include "integrity.h"
#include "worker_protocol.h"
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#if defined(_MSC_VER)
#include <intrin.h>
#elif defined(__x86_64__)
#include <cpuid.h>
#endif
#include <algorithm>
#include <array>
#include <atomic>
#include <condition_variable>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <stdexcept>
#include <string_view>
#include <thread>
#include <utility>
#include <vector>
#ifdef NOTEVIVE_ENGINE_DIAGNOSTICS
#include <iostream>
#endif

namespace doct {
namespace {
constexpr DWORD kRequestPipeBytes = 4096;
constexpr DWORD kExitWaitMs = 5000;
#ifdef NOTEVIVE_SUPERVISOR_TEST
constexpr ULONGLONG kLiveTimeoutMs = 1500;
constexpr ULONGLONG kFinishTimeoutMs = 1500;
constexpr ULONGLONG kCancelTimeoutMs = 500;
#else
constexpr ULONGLONG kLiveTimeoutMs = 90000;
constexpr ULONGLONG kFinishTimeoutMs = 60000;
constexpr ULONGLONG kCancelTimeoutMs = 2000;
#endif
constexpr std::size_t kMaxWavePathUnits = 1024;
static_assert(kMaxWavePathUnits * sizeof(wchar_t) + 3 * wire::header_size < kRequestPipeBytes);
struct Failure { std::wstring text; };
[[noreturn]] void fail(const wchar_t* text) { throw Failure{text}; }
struct Handle {
    HANDLE h = nullptr;
    Handle() = default;
    explicit Handle(HANDLE value) : h(value) {}
    ~Handle() { reset(); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    void reset(HANDLE value = nullptr) {
        if (h && h != INVALID_HANDLE_VALUE) CloseHandle(h);
        h = value;
    }
};

bool processor_supports_avx2() {
#if defined(_M_X64) || defined(__x86_64__)
    // Windows tests both processor instructions and the OS vector state.
    if (!IsProcessorFeaturePresent(PF_AVX_INSTRUCTIONS_AVAILABLE) ||
        !IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE)) return false;
    auto cpuid = [](unsigned leaf) {
        std::array<unsigned, 4> value{};
#ifdef _MSC_VER
        int regs[4]{};
        __cpuidex(regs, static_cast<int>(leaf), 0);
        for (std::size_t i = 0; i < value.size(); ++i) value[i] = static_cast<unsigned>(regs[i]);
#else
        __cpuid_count(leaf, 0, value[0], value[1], value[2], value[3]);
#endif
        return value;
    };
    if (cpuid(0)[0] < 7 || cpuid(0x80000000U)[0] < 0x80000001U) return false;
    constexpr unsigned leaf1 = (1U << 12) | (1U << 20) | (1U << 23) | (1U << 29); // FMA, SSE4.2, POPCNT, F16C
    // /arch:AVX2 can also emit BMI instructions, even if GGML_BMI2 is off.
    constexpr unsigned leaf7 = (1U << 3) | (1U << 5) | (1U << 8); // BMI1, AVX2, BMI2
    return (cpuid(1)[2] & leaf1) == leaf1 && (cpuid(7)[1] & leaf7) == leaf7 &&
        (cpuid(0x80000001U)[2] & (1U << 5)) != 0; // LZCNT/ABM
#else
    return false;
#endif
}

std::wstring execution_directory(const std::wstring& directory) {
    wchar_t mode[9]{};
    if (GetEnvironmentVariableW(L"NOTEVIVE_CPU", mode, std::size(mode)) == 8 &&
        std::wstring_view(mode, 8) == L"baseline") return directory;
    if (!processor_supports_avx2()) return directory;
    const auto candidate = directory + L"\\cpu-avx2";
    const DWORD attributes = GetFileAttributesW(candidate.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES) return directory; // Allows a baseline-only test worker.
    if (!(attributes & FILE_ATTRIBUTE_DIRECTORY) || (attributes & FILE_ATTRIBUTE_REPARSE_POINT))
        fail(L"Le dossier du moteur optimisé est invalide. Réextrayez le paquet complet.");
    return candidate;
}

// The parent never loads ASR code. The child and its capture handles are killed
// with the job when the UI exits or a native call stops responding.
struct Child {
    Handle process, job, input, output;
    bool termination_attempted = false, termination_confirmed = false;
    explicit Child(const std::wstring& directory) {
        const auto root = std::filesystem::path(directory).root_path().wstring();
        const auto drive = GetDriveTypeW(root.c_str());
        if (drive != DRIVE_FIXED && drive != DRIVE_REMOVABLE)
            fail(L"Extrayez NoteVive dans un dossier sur un disque local avant de le lancer.");
        if (!std::filesystem::path(directory).is_absolute() || directory.find(L'"') != std::wstring::npos ||
            !verify_worker_file(directory) || !verify_engine_files(directory))
            fail(L"Le programme de dictée est absent ou altéré. Réextrayez le paquet complet.");
        const auto execution = execution_directory(directory);
#ifdef NOTEVIVE_ENGINE_DIAGNOSTICS
        // Test harness only: aggregate hardware/path diagnostics, never notes or audio.
        SYSTEM_INFO system{};
        GetNativeSystemInfo(&system);
        std::cout << "selected_cpu=" << (execution == directory ? "baseline" : "avx2")
                  << " compatible_avx2=" << processor_supports_avx2()
                  << " os_avx=" << IsProcessorFeaturePresent(PF_AVX_INSTRUCTIONS_AVAILABLE)
                  << " os_avx2=" << IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE)
                  << " logical_processors=" << system.dwNumberOfProcessors << std::endl;
#endif
        if (execution != directory && !verify_worker_file(execution))
            fail(L"Le moteur optimisé est absent ou altéré. Réextrayez le paquet complet.");
        SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
        Handle child_input, child_output, null_error;
        if (!CreatePipe(&child_input.h, &input.h, &security, kRequestPipeBytes) ||
            !CreatePipe(&output.h, &child_output.h, &security, 0) ||
            !SetHandleInformation(input.h, HANDLE_FLAG_INHERIT, 0) ||
            !SetHandleInformation(output.h, HANDLE_FLAG_INHERIT, 0)) fail(L"Impossible de préparer la dictée locale.");
        null_error.reset(CreateFileW(L"NUL", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        if (null_error.h == INVALID_HANDLE_VALUE) fail(L"Impossible de préparer la dictée locale.");
        job.reset(CreateJobObjectW(nullptr, nullptr));
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!job.h || !SetInformationJobObject(job.h, JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
            fail(L"Impossible d’isoler le moteur de dictée.");
        SIZE_T bytes = 0;
        InitializeProcThreadAttributeList(nullptr, 1, 0, &bytes);
        std::vector<unsigned char> storage(bytes);
        auto* attributes = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
        if (!InitializeProcThreadAttributeList(attributes, 1, 0, &bytes)) fail(L"Impossible d’isoler les canaux audio.");
        struct Attributes { LPPROC_THREAD_ATTRIBUTE_LIST p; ~Attributes() { DeleteProcThreadAttributeList(p); } } cleanup{attributes};
        HANDLE inherited[]{child_input.h, child_output.h, null_error.h};
        if (!UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            inherited, sizeof(inherited), nullptr, nullptr)) fail(L"Impossible d’isoler les canaux audio.");
        STARTUPINFOEXW startup{};
        startup.StartupInfo.cb = sizeof(startup);
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = child_input.h;
        startup.StartupInfo.hStdOutput = child_output.h;
        startup.StartupInfo.hStdError = null_error.h;
        startup.lpAttributeList = attributes;
        const auto executable = execution + L"\\NoteVive-ASR.exe";
        // A trailing slash must not escape the final command-line quote.
        const auto normalized = std::filesystem::path(directory).lexically_normal().wstring();
        auto command = L"\"" + executable + L"\" \"" + normalized +
            (normalized.back() == L'\\' ? L"\\\"" : L"\"");
        PROCESS_INFORMATION info{};
        if (!CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, TRUE,
            CREATE_NO_WINDOW | CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT,
            nullptr, directory.c_str(), &startup.StartupInfo, &info))
            fail(L"Impossible de lancer le moteur local. Vérifiez le paquet et les règles du poste.");
        process.reset(info.hProcess);
        Handle thread(info.hThread);
        if (!AssignProcessToJobObject(job.h, process.h) || ResumeThread(thread.h) == static_cast<DWORD>(-1)) {
            TerminateProcess(process.h, 1); WaitForSingleObject(process.h, kExitWaitMs);
            fail(L"Impossible de superviser le moteur de dictée.");
        }
    }
    bool terminate() {
        if (!termination_attempted) {
            termination_attempted = true;
            if (job.h) TerminateJobObject(job.h, 0);
            termination_confirmed = !process.h || WaitForSingleObject(process.h, kExitWaitMs) == WAIT_OBJECT_0;
        }
        return termination_confirmed;
    }
    ~Child() { terminate(); }
    bool send(wire::Kind kind, std::uint64_t generation, const std::wstring& payload = {}, std::uint32_t flags = 0) {
        // Requests contain no audio. Keep each write below the pipe buffer so
        // a stalled child cannot hold the supervisor inside a synchronous send.
        if (payload.size() > kMaxWavePathUnits) fail(L"Le chemin du fichier de test est trop long.");
        auto header = wire::encode({kind, generation, static_cast<std::uint32_t>(payload.size() * 2), flags});
        auto write = [&](const void* data, DWORD count) {
            DWORD done = 0;
            return !count || (WriteFile(input.h, data, count, &done, nullptr) && done == count);
        };
        return write(header.data(), static_cast<DWORD>(header.size())) &&
            write(payload.data(), static_cast<DWORD>(payload.size() * 2));
    }
};
struct Session {
    std::uint64_t generation;
    std::wstring directory, wave;
    std::atomic<int> stop{0}; // 0 live, 1 finish, 2 cancel
    Session(std::uint64_t g, std::wstring d, std::wstring w)
        : generation(g), directory(std::move(d)), wave(std::move(w)) {}
};
}

struct Engine::Impl {
    Callback callback;
    std::mutex mutex;
    std::condition_variable changed;
    std::shared_ptr<Session> active;
    bool closed = false, capture_blocked = false;
    std::unique_ptr<Child> child;
    std::wstring child_directory;
    std::thread worker;
    explicit Impl(Callback f) : callback(std::move(f)), worker([this] { run(); }) {}
    ~Impl() { shutdown(); }
    void emit(const Session& s, EngineEventKind kind, std::wstring text = {}, bool unconfirmed = false) noexcept {
        try { callback({kind, s.generation, std::move(text), unconfirmed}); } catch (...) {}
    }
    void remove_child() {
        if (!child) return;
        const bool confirmed = child->terminate();
        child.reset();
        if (!confirmed) { std::lock_guard<std::mutex> lock(mutex); capture_blocked = true; }
    }
    bool start(std::uint64_t generation, std::wstring directory, std::wstring wave) {
        std::lock_guard<std::mutex> lock(mutex);
        if (closed || active || capture_blocked || !generation) return false;
        try { active = std::make_shared<Session>(generation, std::move(directory), std::move(wave)); }
        catch (...) { return false; }
        changed.notify_one(); return true;
    }
    void stop(int mode) {
        std::lock_guard<std::mutex> lock(mutex);
        if (active && active->stop.load() < mode) active->stop.store(mode);
    }
    void shutdown() {
        { std::lock_guard<std::mutex> lock(mutex); closed = true; if (active) active->stop.store(2); }
        changed.notify_one();
        if (worker.joinable()) worker.join();
    }
    void process(Session& s) {
        if (s.stop.load()) return;
        if (!child || child_directory != s.directory || WaitForSingleObject(child->process.h, 0) != WAIT_TIMEOUT) {
            remove_child();
            { std::lock_guard<std::mutex> lock(mutex);
              if (capture_blocked) fail(L"Arrêt du microphone non confirmé. Fermez NoteVive."); }
            child = std::make_unique<Child>(s.directory); child_directory = s.directory;
        }
        // Verification and process startup may take seconds on a cold disk.
        // Do not send a start command if Cancel/lock arrived meanwhile.
        if (s.stop.load()) return;
        if (!child->send(wire::start, s.generation, s.wave, s.wave.empty() ? 0 : 1))
            fail(L"Le moteur local s’est arrêté. Le texte déjà confirmé est conservé.");
        int sent_stop = 0;
        ULONGLONG deadline = GetTickCount64() + kLiveTimeoutMs;
        std::vector<std::uint8_t> frame(wire::header_size);
        std::size_t received = 0;
        wire::Header header{};
        bool reading_header = true;
        const auto pipe_ended = [&] {
            if (!reading_header || received) fail(L"Le moteur a transmis un passage incomplet. Le texte déjà confirmé est conservé.");
            fail(L"Le moteur s’est interrompu. Le texte déjà confirmé est conservé ; vous pouvez relancer la dictée.");
        };
#ifdef NOTEVIVE_SUPERVISOR_TEST
        bool fixture_released = false;
#endif
        for (;;) {
            const int requested = s.stop.load();
            if (requested > sent_stop) {
                sent_stop = requested;
                const bool delivered = child->send(requested == 2 ? wire::cancel : wire::stop, s.generation);
                // The child may have closed the input while its final frame is
                // still available on stdout. Drain before reporting a crash.
                deadline = GetTickCount64() +
                    (!delivered || requested == 2 ? kCancelTimeoutMs : kFinishTimeoutMs);
            }
            if (deadline && GetTickCount64() > deadline) {
                remove_child();
                if (requested == 2) return;
                fail(L"Le moteur n’a pas terminé à temps. Le texte déjà confirmé est conservé ; vous pouvez relancer la dictée.");
            }
            DWORD available = 0;
            if (!PeekNamedPipe(child->output.h, nullptr, 0, nullptr, &available, nullptr)) pipe_ended();
            if (!available) {
                DWORD poll_ms = 25;
#ifdef NOTEVIVE_SUPERVISOR_TEST
                if (!fixture_released && s.wave == L"truncated") {
                    // Reproduce the exit race with the fixture: release the child
                    // only after the first empty peek, then wait for its exit.
                    fixture_released = true;
                    if (!child->send(wire::stop, s.generation)) fail(L"Le test du canal n’a pas pu démarrer.");
                    poll_ms = static_cast<DWORD>(kLiveTimeoutMs);
                }
#endif
                const DWORD wait = WaitForSingleObject(child->process.h, poll_ms);
                if (wait == WAIT_TIMEOUT) continue;
                // Data can arrive after the empty peek and before the process
                // exits. Read complete frames before reporting the failure.
                if (wait != WAIT_OBJECT_0 ||
                    !PeekNamedPipe(child->output.h, nullptr, 0, nullptr, &available, nullptr) || !available)
                    pipe_ended();
            }
            const auto count = static_cast<DWORD>(std::min<std::size_t>(available, frame.size() - received));
            DWORD done = 0;
            if (!ReadFile(child->output.h, frame.data() + received, count, &done, nullptr) || !done)
                fail(L"Le moteur a fermé son canal de dictée.");
            received += done;
            if (received != frame.size()) continue;
            if (reading_header) {
                std::array<std::uint8_t, wire::header_size> bytes{};
                std::copy(frame.begin(), frame.end(), bytes.begin()); header = wire::decode(bytes);
                if (header.kind < wire::started || header.generation != s.generation)
                    fail(L"Réponse inattendue du moteur de dictée.");
                if (((header.kind == wire::started || header.kind == wire::capture_stopped ||
                      header.kind == wire::progress) && (header.bytes || header.flags)) ||
                    (header.kind == wire::stopped && header.bytes))
                    fail(L"État du moteur de dictée invalide.");
                reading_header = false; received = 0; frame.resize(header.bytes);
                if (header.bytes) continue;
            }
            std::wstring text(frame.size() / 2, L'\0');
            if (!frame.empty()) std::memcpy(text.data(), frame.data(), frame.size());
            if (text.find(L'\0') != std::wstring::npos) fail(L"Réponse illisible du moteur de dictée.");
            const auto kind = static_cast<EngineEventKind>(header.kind - wire::started);
            if ((header.kind == wire::started || header.kind == wire::progress) && !sent_stop)
                deadline = GetTickCount64() + kLiveTimeoutMs;
            if (wire::terminal(header.kind)) {
                if (header.flags) remove_child();
                if (kind == EngineEventKind::error) {
                    if (text.empty()) fail(L"Le moteur local a échoué. Le texte déjà confirmé est conservé.");
                    throw Failure{std::move(text)};
                }
                return;
            }
            if (s.stop.load() != 2 && header.kind != wire::progress) emit(s, kind, std::move(text), header.flags != 0);
            frame.resize(wire::header_size); reading_header = true; received = 0;
        }
    }
    void run() {
        for (;;) {
            std::shared_ptr<Session> s;
            { std::unique_lock<std::mutex> lock(mutex); changed.wait(lock, [&] { return closed || active; });
              if (!active) break; s = active; }
            std::wstring error;
            try { process(*s); }
            catch (const Failure& e) { error = e.text; remove_child(); }
            catch (...) { error = L"Le moteur local a échoué. Le texte déjà confirmé est conservé."; remove_child(); }
            bool unconfirmed;
            { std::lock_guard<std::mutex> lock(mutex); active.reset(); unconfirmed = capture_blocked; }
            if (unconfirmed) error = L"Arrêt du microphone non confirmé. Fermez NoteVive avant tout nouvel essai.";
            const auto terminal = error.empty() ? EngineEventKind::stopped : EngineEventKind::error;
            emit(*s, terminal, std::move(error), unconfirmed);
        }
        remove_child();
    }
};
Engine::Engine(Callback callback) : impl_(std::make_unique<Impl>(std::move(callback))) {}
Engine::~Engine() = default;
bool Engine::start(std::uint64_t generation, std::wstring directory) { return impl_->start(generation, std::move(directory), {}); }
bool Engine::start_wave(std::uint64_t generation, std::wstring directory, std::wstring wave) {
    return !wave.empty() && impl_->start(generation, std::move(directory), std::move(wave));
}
void Engine::stop() { impl_->stop(1); }
void Engine::cancel() { impl_->stop(2); }
void Engine::shutdown() { impl_->shutdown(); }
}
