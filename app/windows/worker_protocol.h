#pragma once
#include <array>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>

namespace doct::wire {
// Local anonymous pipes only. Explicit little-endian fields, bounded UTF-16LE
// payloads; no object pointers, filenames of recordings or credentials.
constexpr std::size_t header_size = 24, max_bytes = 128 * 1024;
enum Kind : std::uint32_t { start = 1, stop, cancel, quit,
    started = 16, partial, final, capture_stopped, stopped, error, progress };
struct Header { Kind kind; std::uint64_t generation; std::uint32_t bytes, flags; };
inline void put(std::uint8_t* p, std::uint64_t n, int size) {
    for (int i = 0; i < size; ++i) p[i] = static_cast<std::uint8_t>(n >> (8 * i));
}
inline std::uint64_t get(const std::uint8_t* p, int size) {
    std::uint64_t n = 0;
    for (int i = 0; i < size; ++i) n |= std::uint64_t(p[i]) << (8 * i);
    return n;
}
inline std::array<std::uint8_t, header_size> encode(Header h) {
    std::array<std::uint8_t, header_size> b{};
    put(b.data(), 0x3157564e, 4); // NVW1
    put(b.data() + 4, h.kind, 4); put(b.data() + 8, h.generation, 8);
    put(b.data() + 16, h.bytes, 4); put(b.data() + 20, h.flags, 4);
    return b;
}
inline Header decode(const std::array<std::uint8_t, header_size>& b) {
    const auto k = get(b.data() + 4, 4);
    Header h{static_cast<Kind>(k), get(b.data() + 8, 8),
        static_cast<std::uint32_t>(get(b.data() + 16, 4)),
        static_cast<std::uint32_t>(get(b.data() + 20, 4))};
    if (get(b.data(), 4) != 0x3157564e || h.bytes > max_bytes || h.bytes % 2 || h.flags > 1 ||
        !((k >= start && k <= quit) || (k >= started && k <= progress)))
        throw std::runtime_error("Protocole de dictee invalide");
    return h;
}
inline bool terminal(Kind k) { return k == stopped || k == error; }
}
