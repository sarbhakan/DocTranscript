"""Hash-locked upstream fixes, shared by the Windows build and offline experiments."""
import hashlib


DECODER_PATCH = {
    "path": "src/whisper.cpp",
    "upstream_commit": "6d0ed914991cac42ace012a05588880801831343",
    "upstream_url": "https://github.com/ggml-org/whisper.cpp/commit/6d0ed914991cac42ace012a05588880801831343",
    "before_sha256": "42d04939f00cd8db5ad3267af0f2a377f34b86a5d9ba45ed21795f668542615d",
    "after_sha256": "3c7067dae7b77832053b4c4e21ab93b9cb732fe9825194fc69a7d20d5e52a861",
}


def patched_decoder(before):
    # Upstream #4025 resets decoder 0 as well as the other decoders on every
    # call. Without this, temperature fallback depends on earlier dictations
    # in the same context. Preserve every other decoding parameter and weight.
    marker = b"    // TAGS: WHISPER_DECODER_INIT\n    for (int j = 1; j < n_decoders; j++) {"
    after = before.replace(marker, b"    state->decoders[0].rng = std::mt19937(0);\n\n" + marker, 1)
    if (before.count(marker) != 1
            or hashlib.sha256(before).hexdigest() != DECODER_PATCH["before_sha256"]
            or hashlib.sha256(after).hexdigest() != DECODER_PATCH["after_sha256"]):
        raise ValueError("Le correctif du décodeur ne correspond pas aux sources Whisper verrouillées.")
    return after


def edit_decoder(path):
    path.write_bytes(patched_decoder(path.read_bytes()))
    return DECODER_PATCH.copy()
