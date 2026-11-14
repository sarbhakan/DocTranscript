#include "local_engine.h"
#include "integrity.h"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <mmsystem.h>

#include "../native/WhisperBridge.h"

#include <algorithm>
#include <array>
#include <condition_variable>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <mutex>
#include <thread>
#include <utility>

namespace doct {
namespace {

constexpr int kRate = 16000;
constexpr int kPacketSamples = 320; // 20 ms
constexpr std::size_t kDriverBuffers = 8;
constexpr std::size_t kQueuePackets = 30 * kRate / kPacketSamples; // Bounded backlog during CPU decoding
constexpr DWORD kNoAudioTimeoutMs = 4000;
using Event = EngineEventKind;

struct Failure { std::wstring message; };

[[noreturn]] void fail(std::wstring message) { throw Failure{std::move(message)}; }

class Signal {
public:
    Signal() : value_(CreateEventW(nullptr, FALSE, FALSE, nullptr)) {
        if (!value_) fail(L"Impossible de préparer la capture audio.");
    }
    ~Signal() { CloseHandle(value_); }
    Signal(const Signal&) = delete;
    Signal& operator=(const Signal&) = delete;
    HANDLE get() const { return value_; }
    void set() const { SetEvent(value_); }
private:
    HANDLE value_;
};

std::string utf8(const std::wstring& value) {
    if (value.size() > static_cast<std::size_t>(std::numeric_limits<int>::max()))
        fail(L"Le chemin du moteur est trop long.");
    const auto size = static_cast<int>(value.size());
    const int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), size,
                                     nullptr, 0, nullptr, nullptr);
    if (!n) fail(L"Le chemin du moteur ne peut pas être lu.");
    std::string result(static_cast<std::size_t>(n), '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), size,
                            result.data(), n, nullptr, nullptr) != n)
        fail(L"Le chemin du moteur ne peut pas être lu.");
    return result;
}

std::wstring wide_text(const char* value) {
    if (!value || !*value) return {};
    const int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value, -1, nullptr, 0);
    if (n < 1) fail(L"Le moteur a produit un texte illisible.");
    std::wstring text(static_cast<std::size_t>(n), L'\0');
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value, -1, text.data(), n) != n)
        fail(L"Le moteur a produit un texte illisible.");
    text.resize(static_cast<std::size_t>(n - 1));
    const auto start = text.find_first_not_of(L" \r\n\t");
    if (start == std::wstring::npos) return {};
    const auto end = text.find_last_not_of(L" \r\n\t");
    return text.substr(start, end - start + 1);
}

struct Runtime {
    using Path = std::filesystem::path;
    const Path directory;
    void* handle = nullptr;
    explicit Runtime(const Path& directory) : directory(directory) {
        if (!directory.is_absolute() || !verify_engine_files(directory.wstring()))
            fail(L"Les fichiers du moteur ne correspondent pas au paquet. Réextrayez le ZIP complet.");
        const auto model = utf8((directory / L"ggml-large-v3-turbo-q5_0.bin").wstring());
        const auto vad = utf8((directory / L"ggml-silero-v6.2.0.bin").wstring());
        handle = NVWhisperCreate(model.c_str(), vad.c_str());
        if (!handle) fail(L"Whisper n’a pas pu charger le modèle local. Vérifiez la mémoire disponible.");
    }
    ~Runtime() { NVWhisperDestroy(handle); }
    Runtime(const Runtime&) = delete;
    Runtime& operator=(const Runtime&) = delete;
};

struct Packet {
    std::array<std::int16_t, kPacketSamples> samples{};
    int count = 0;
};

enum class Stop { no, finish, discard };

struct Session {
    Session(std::uint64_t generation, std::wstring directory, std::wstring wave)
        : generation(generation), directory(std::move(directory)), wave(std::move(wave)) {}
    const std::uint64_t generation;
    const std::wstring directory;
    const std::wstring wave;
    Signal stop_event;
    std::mutex mutex;
    std::condition_variable changed;
    Stop stop = Stop::no;
    std::array<Packet, kQueuePackets> queue{};
    std::size_t head = 0, used = 0;
    bool capture_done = false, close_unconfirmed = false;
    std::wstring capture_error;

    void request(Stop mode) {
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (stop == Stop::no || mode == Stop::discard) stop = mode;
            if (stop == Stop::discard) used = 0;
        }
        stop_event.set();
        changed.notify_one();
    }
    Stop mode() {
        std::lock_guard<std::mutex> lock(mutex);
        return stop;
    }
    bool push(const std::int16_t* samples, int count) {
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (stop == Stop::discard) return true;
            if (used == queue.size()) return false;
            auto& packet = queue[(head + used) % queue.size()];
            std::copy_n(samples, count, packet.samples.begin());
            packet.count = count;
            ++used;
        }
        changed.notify_one();
        return true;
    }
};

void check_mm(MMRESULT result, const wchar_t* action) {
    if (result != MMSYSERR_NOERROR)
        fail(std::wstring(action) + L" (code audio " + std::to_wstring(result) + L").");
}

struct Capture {
    struct Buffer { std::array<std::int16_t, kPacketSamples> samples{}; WAVEHDR header{}; bool prepared = false; };
    Signal ready;
    HWAVEIN device = nullptr;
    std::array<Buffer, kDriverBuffers> buffers{};
    std::size_t head = 0;

    void open() {
        WAVEFORMATEX format{};
        format.wFormatTag = WAVE_FORMAT_PCM;
        format.nChannels = 1;
        format.nSamplesPerSec = kRate;
        format.wBitsPerSample = 16;
        format.nBlockAlign = 2;
        format.nAvgBytesPerSec = kRate * 2;
        HWAVEIN opened = nullptr;
        check_mm(waveInOpen(&opened, WAVE_MAPPER, &format,
                            reinterpret_cast<DWORD_PTR>(ready.get()), 0, CALLBACK_EVENT),
                 L"Microphone indisponible. Vérifiez le périphérique et les autorisations Windows");
        device = opened;
        for (auto& buffer : buffers) {
            buffer.header.lpData = reinterpret_cast<LPSTR>(buffer.samples.data());
            buffer.header.dwBufferLength = static_cast<DWORD>(buffer.samples.size() * sizeof(std::int16_t));
            check_mm(waveInPrepareHeader(device, &buffer.header, sizeof(WAVEHDR)),
                     L"Impossible de préparer le tampon du microphone");
            buffer.prepared = true;
            check_mm(waveInAddBuffer(device, &buffer.header, sizeof(WAVEHDR)),
                     L"Impossible de lire le microphone");
        }
    }
    void collect(Session& session, bool requeue) {
        const bool starved = requeue && std::all_of(buffers.begin(), buffers.end(), [](const Buffer& b) {
            return (b.header.dwFlags & WHDR_DONE) != 0;
        });
        // If the driver exhausted its buffers, preserve the last contiguous
        // packets without accepting new audio across a possible gap.
        if (starved) requeue = false;
        for (std::size_t i = 0; i < buffers.size(); ++i) {
            if (requeue && session.mode() != Stop::no) break;
            auto& buffer = buffers[head];
            if (!(buffer.header.dwFlags & WHDR_DONE)) break;
            const DWORD bytes = buffer.header.dwBytesRecorded;
            if (bytes > buffer.header.dwBufferLength || bytes % sizeof(std::int16_t) != 0)
                fail(L"Le microphone a renvoyé des données invalides.");
            if (bytes && !session.push(buffer.samples.data(), static_cast<int>(bytes / sizeof(std::int16_t))))
                fail(L"Le moteur n’a pas suivi la dictée. Dictée interrompue pour éviter une perte silencieuse.");
            head = (head + 1) % buffers.size();
            if (requeue) {
                buffer.header.dwBytesRecorded = 0;
                check_mm(waveInAddBuffer(device, &buffer.header, sizeof(WAVEHDR)),
                         L"Le microphone a été déconnecté ou n’est plus disponible");
            }
        }
        if (starved)
            fail(L"Le microphone n’a pas pu être lu à temps. Dictée interrompue pour éviter une perte silencieuse.");
    }
    bool close() noexcept {
        if (!device) return true;
        for (int attempt = 0; attempt < 3; ++attempt) {
            if (attempt) Sleep(10);
            waveInReset(device);
            for (auto& b : buffers) {
                if (b.prepared && waveInUnprepareHeader(device, &b.header, sizeof(WAVEHDR)) == MMSYSERR_NOERROR)
                    b.prepared = false;
            }
            if (waveInClose(device) == MMSYSERR_NOERROR) {
                device = nullptr;
                return true;
            }
        }
        return false;
    }
};

template <class Started, class Stopped>
void capture_audio(Session& session, Started started, Stopped stopped) {
    std::unique_ptr<Capture> mic;
    std::wstring error;
    bool opened = false, close_unconfirmed = false;
    try {
        if (session.mode() == Stop::no) {
            mic = std::make_unique<Capture>();
            mic->open();
            if (session.mode() == Stop::no) {
                check_mm(waveInStart(mic->device), L"Impossible de démarrer le microphone");
                opened = true;
                started(); // Report the actual device state before queuing any audio.
                const HANDLE waits[]{session.stop_event.get(), mic->ready.get()};
                while (session.mode() == Stop::no) {
                    const DWORD outcome = WaitForMultipleObjects(2, waits, FALSE, kNoAudioTimeoutMs);
                    if (outcome == WAIT_OBJECT_0) break;
                    if (outcome != WAIT_OBJECT_0 + 1)
                        fail(L"Le microphone ne transmet plus de données.");
                    mic->collect(session, true);
                }
                // Stop records the byte count of the last partially filled buffer.
                // Reset then returns the other queued buffers and lets us close.
                if (session.mode() == Stop::finish)
                    check_mm(waveInStop(mic->device), L"Impossible d’arrêter le microphone");
                check_mm(waveInReset(mic->device), L"Impossible d’arrêter le microphone");
                if (session.mode() == Stop::finish) mic->collect(session, false);
            }
        }
    } catch (const Failure& e) {
        error = e.message;
    } catch (...) {
        error = L"Erreur pendant la capture du microphone.";
    }
    if (mic && !mic->close()) {
        // A faulty driver may still reference these buffers or the event. Keep
        // them alive until process exit and forbid further capture attempts.
        (void)mic.release();
        close_unconfirmed = true;
        error = L"Arrêt du microphone non confirmé. Fermez l’application.";
    }
    // The recognizer may still be busy with an earlier segment. Tell the UI
    // that the device is closed without waiting for it, before any terminal event.
    if (opened && !close_unconfirmed) stopped();
    {
        std::lock_guard<std::mutex> lock(session.mutex);
        session.capture_done = true;
        session.close_unconfirmed = close_unconfirmed;
        session.capture_error = std::move(error);
    }
    session.changed.notify_one();
}

std::uint16_t u16(const char* p) {
    return static_cast<std::uint16_t>(static_cast<unsigned char>(p[0]) |
                                     (static_cast<unsigned char>(p[1]) << 8));
}
std::uint32_t u32(const char* p) {
    return u16(p) | (static_cast<std::uint32_t>(u16(p + 2)) << 16);
}

// Smoke fixtures are short, standard RIFF PCM. Check lengths before reading
// samples; the app never writes or retains a WAV from the microphone.
class WaveFixture {
public:
    explicit WaveFixture(const std::wstring& name) : file_(std::filesystem::path(name), std::ios::binary) {
        constexpr std::uint32_t max_pcm = kRate * 2 * 60;
        char header[12]{};
        if (!file_.read(header, sizeof(header)) || std::memcmp(header, "RIFF", 4) ||
            std::memcmp(header + 8, "WAVE", 4)) invalid();
        const auto size = u32(header + 4);
        if (size < 36 || size > max_pcm + 65536) invalid();
        file_.seekg(0, std::ios::end);
        if (file_.tellg() != static_cast<std::streamoff>(size) + 8) invalid();
        file_.seekg(12);
        bool format = false;
        std::uint32_t remaining = size - 4;
        while (remaining >= 8) {
            char chunk[8]{};
            if (!file_.read(chunk, sizeof(chunk))) invalid();
            const auto bytes = u32(chunk + 4);
            remaining -= 8;
            if (bytes > remaining || (bytes & 1U) > remaining - bytes) invalid();
            const auto padded = bytes + (bytes & 1U);
            if (!std::memcmp(chunk, "fmt ", 4)) {
                char fmt[16]{};
                if (format || bytes < sizeof(fmt) || !file_.read(fmt, sizeof(fmt)) ||
                    u16(fmt) != 1 || u16(fmt + 2) != 1 || u32(fmt + 4) != kRate ||
                    u32(fmt + 8) != kRate * 2 || u16(fmt + 12) != 2 || u16(fmt + 14) != 16) invalid();
                format = true;
                file_.seekg(padded - sizeof(fmt), std::ios::cur);
            } else if (!std::memcmp(chunk, "data", 4)) {
                if (!format || !bytes || bytes > max_pcm || bytes % 2) invalid();
                samples_left_ = bytes / 2;
                return;
            } else {
                file_.seekg(padded, std::ios::cur);
            }
            remaining -= padded;
        }
        invalid();
    }
    bool next(Packet& packet) {
        if (!samples_left_) return false;
        const auto count = std::min(samples_left_, static_cast<std::uint32_t>(kPacketSamples));
        if (!file_.read(reinterpret_cast<char*>(packet.samples.data()), count * sizeof(std::int16_t))) invalid();
        packet.count = static_cast<int>(count);
        samples_left_ -= count;
        return true;
    }
private:
    [[noreturn]] static void invalid() { fail(L"Le test attend un fichier WAV PCM 16 bits mono à 16 kHz, de 60 secondes maximum."); }
    std::ifstream file_;
    std::uint32_t samples_left_ = 0;
};

} // namespace

struct LocalEngine::Impl {
    explicit Impl(Callback callback, std::function<void()> pulse)
        : callback(std::move(callback)), progress(std::move(pulse)), worker([this] { run(); }) {}
    ~Impl() { shutdown(); }

    Callback callback;
    std::function<void()> progress;
    ULONGLONG last_progress = 0;
    void pulse() {
        const auto now = GetTickCount64();
        if (now - last_progress >= 1000) { last_progress = now; if (progress) progress(); }
    }
    std::mutex mutex;
    std::condition_variable requested;
    std::shared_ptr<Session> active;
    bool closed = false;
    bool capture_blocked = false;
    std::unique_ptr<Runtime> runtime;
    std::thread worker; // initialized after every object used by run()

    bool start(std::uint64_t generation, std::wstring directory, std::wstring wave) {
        std::lock_guard<std::mutex> lock(mutex);
        if (active || closed || (wave.empty() && capture_blocked)) return false;
        try {
            active = std::make_shared<Session>(generation, std::move(directory), std::move(wave));
        } catch (...) {
            return false;
        }
        requested.notify_one();
        return true;
    }
    void stop(Stop mode) {
        std::lock_guard<std::mutex> lock(mutex);
        if (active) active->request(mode);
    }
    void shutdown() {
        {
            std::lock_guard<std::mutex> lock(mutex);
            closed = true;
            if (active) active->request(Stop::discard);
        }
        requested.notify_one();
        if (worker.joinable()) worker.join();
    }
    void emit(const Session& session, Event kind, std::wstring text = {},
              bool capture_unconfirmed = false) noexcept {
        // No exceptions may cross into capture or prevent release of a device.
        try { if (callback) callback(EngineEvent{kind, session.generation, std::move(text), capture_unconfirmed}); }
        catch (...) {}
    }

    struct Decoder {
        Impl& owner;
        Session& session;
        Runtime& runtime;
        Decoder(Impl& owner, Session& session, Runtime& runtime)
            : owner(owner), session(session), runtime(runtime) {
            NVWhisperReset(runtime.handle);
            NVWhisperSetCancellation(runtime.handle, [](void* ctx) {
                return static_cast<Session*>(ctx)->mode() == Stop::discard ? 1 : 0;
            }, &session);
        }
        ~Decoder() { NVWhisperSetCancellation(runtime.handle, nullptr, nullptr); NVWhisperReset(runtime.handle); }
        static int complete(void* context, const char* text, std::size_t, double) {
            auto& self = *static_cast<Decoder*>(context);
            if (self.session.mode() == Stop::discard) return -1;
            auto result = wide_text(text);
            if (self.session.mode() == Stop::discard) return -1;
            if (!result.empty()) self.owner.emit(self.session, Event::final, std::move(result));
            return 0;
        }
        void feed(const Packet& packet) {
            if (session.mode() == Stop::discard) return;
            std::array<float, kPacketSamples> normalized{};
            for (int i = 0; i < packet.count; ++i) normalized[i] = static_cast<float>(packet.samples[i]) / 32768.f;
            if (NVWhisperAccept(runtime.handle, normalized.data(), packet.count, complete, this) != 0 &&
                session.mode() != Stop::discard) fail(L"La transcription locale a échoué. Le texte confirmé reste dans la note.");
        }
        void finish() {
            if (session.mode() != Stop::discard && NVWhisperFinish(runtime.handle, complete, this) != 0 &&
                session.mode() != Stop::discard) fail(L"Impossible de terminer la dernière phrase.");
        }
    };

    void run_capture(Session& session, Decoder& decoder) {
        std::thread capture([&] {
            capture_audio(session, [&] { emit(session, Event::started); },
                          [&] { emit(session, Event::capture_stopped); });
        });
        try {
            for (;;) {
                Packet packet;
                bool done, unconfirmed;
                std::wstring error;
                {
                    std::unique_lock<std::mutex> lock(session.mutex);
                    session.changed.wait(lock, [&] { return session.capture_done || session.used; });
                    done = session.capture_done;
                    unconfirmed = session.close_unconfirmed;
                    if (session.used && !unconfirmed && session.stop != Stop::discard) {
                        packet = session.queue[session.head];
                        session.head = (session.head + 1) % session.queue.size();
                        --session.used;
                    } else if (done) {
                        error = std::move(session.capture_error);
                    }
                }
                if (packet.count) { decoder.feed(packet); pulse(); }
                else if (done) {
                    if (!error.empty()) {
                        // The driver closed. A disconnection or a full queue
                        // does not invalidate the contiguous audio already read.
                        if (!unconfirmed && session.mode() != Stop::discard) {
                            try { decoder.finish(); } catch (...) {
                                error += L" La dernière phrase n’a pas pu être terminée.";
                            }
                        }
                        fail(std::move(error));
                    }
                    break;
                }
            }
        } catch (...) {
            session.request(Stop::discard);
            capture.join();
            if (session.close_unconfirmed) {
                {
                    std::lock_guard<std::mutex> lock(mutex);
                    capture_blocked = true;
                }
                fail(L"Arrêt du microphone non confirmé. Fermez l’application.");
            }
            throw;
        }
        capture.join();
    }
    void process(Session& session) {
        if (session.mode() != Stop::no) return;
        auto path = std::filesystem::path(session.directory);
        path.make_preferred();
        if (!runtime || runtime->directory != path) {
            runtime.reset();
            runtime = std::make_unique<Runtime>(path);
        }
        if (session.mode() != Stop::no) return;
        Decoder decoder(*this, session, *runtime);
        if (session.wave.empty()) {
            run_capture(session, decoder);
        } else {
            WaveFixture input(session.wave);
            Packet packet;
            while (session.mode() == Stop::no && input.next(packet)) { decoder.feed(packet); pulse(); }
        }
        decoder.finish();
    }
    void run() {
        for (;;) {
            std::shared_ptr<Session> session;
            {
                std::unique_lock<std::mutex> lock(mutex);
                requested.wait(lock, [&] { return closed || active; });
                if (!active) break;
                session = active;
            }
            Event terminal = Event::stopped;
            std::wstring error;
            try {
                process(*session);
            } catch (Failure& e) {
                terminal = Event::error;
                error = std::move(e.message);
            } catch (...) {
                terminal = Event::error;
                error = L"Impossible de terminer la dictée locale.";
            }
            {
                std::lock_guard<std::mutex> lock(mutex);
                active.reset();
            }
            emit(*session, terminal, std::move(error), session->close_unconfirmed);
        }
        runtime.reset();
    }
};

LocalEngine::LocalEngine(Callback callback, std::function<void()> progress)
    : impl_(std::make_unique<Impl>(std::move(callback), std::move(progress))) {}
LocalEngine::~LocalEngine() = default;
bool LocalEngine::start(std::uint64_t generation, std::wstring model_directory) {
    return impl_->start(generation, std::move(model_directory), {});
}
bool LocalEngine::start_wave(std::uint64_t generation, std::wstring model_directory, std::wstring wave_path) {
    return !wave_path.empty() && impl_->start(generation, std::move(model_directory), std::move(wave_path));
}
void LocalEngine::stop() { impl_->stop(Stop::finish); }
void LocalEngine::cancel() { impl_->stop(Stop::discard); }
void LocalEngine::shutdown() { impl_->shutdown(); }

} // namespace doct
