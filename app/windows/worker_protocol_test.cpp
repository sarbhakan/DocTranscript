#include "worker_protocol.h"
#ifdef NDEBUG
#error "Protocol checks require assertions enabled"
#endif
#include <cassert>
#include <iostream>
int main() {
    using namespace doct::wire;
    const auto h = decode(encode({final, 0xfedcba9876543210ULL, 128, 0}));
    assert(h.kind == final && h.generation == 0xfedcba9876543210ULL && h.bytes == 128);
    auto rejected = [](auto bytes) { try { (void)decode(bytes); return false; } catch (...) { return true; } };
    assert(rejected(encode({final, 1, max_bytes + 2, 0})));
    assert(rejected(encode({final, 1, 3, 0})));
    assert(rejected(encode({static_cast<Kind>(15), 1, 0, 0})));
    assert(rejected(encode({started, 1, 0, 2})));
    auto version = encode({start, 1, 0, 0}); version[3] = '9'; assert(rejected(version));
    assert(terminal(stopped) && terminal(error) && !terminal(final));
    assert(valid_text(L"Œdème\r\n\t1/2"));
    assert(valid_text(std::wstring{L'x', 0xd83d, 0xde00}));
    assert(!valid_text(std::wstring{L'x', L'\0', L'y'}));
    assert(!valid_text(L"un\x85 mot"));
    assert(!valid_text(std::wstring{0xd83d}));
    assert(!valid_text(std::wstring{0xde00, 0xd83d}));
    std::cout << "Protocol bounds, framing, Unicode and event identity: OK\n";
}
