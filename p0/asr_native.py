"""Thin bindings to the native NoteVive/Sherpa replay helpers; used only by the ASR bench."""
import ctypes as c
import hashlib
import os
from time import perf_counter
import wave


PTR = c.c_void_p
PCM = c.POINTER(c.c_float)
EMIT = c.CFUNCTYPE(c.c_int, PTR, PCM, c.c_size_t)
WHISPER_EMIT = c.CFUNCTYPE(c.c_int, PTR, c.c_char_p, c.c_size_t, c.c_double)
ZIPFORMER_LOCK = {
    "encoder.onnx": "47a94a7fdc8dff63d708be4ea0535747640224467f91e238311f1ddbdd09327e",
    "decoder.onnx": "3ef2840b684440e26382af87b2174d25732a9f113f1965cd8abba7ffc5d033fb",
    "joiner.onnx": "fc2f3bb851a15a532c6f2422d53eecd1ca949f12b0897e07a852021c30481711",
    "tokens.txt": "37fb3f2a7bcb85e5fff3f1f66be04e6fbb05077a22f56d177fe85704e945fb31",
}
ULTIMED_LOCK = {
    "decoder_joint-model.int8.onnx": "5c621d9d3769505c764e7c2de0c7508427cc1afdba73e1174003d52d4b784468",
    "encoder-model.int8.onnx": "f524b0d415dd142502fd504fb7dfe722f455edbe280131ac8fadf9eab3af23a3",
    "nemo128.onnx": "a9fde1486ebfcc08f328d75ad4610c67835fea58c73ba57e3209a6f6cf019e9f",
    "silero_vad.onnx": "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
    "vocab.txt": "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d",
}


def verify_pack(directory, locked, vad):
    for name, sha in locked.items():
        path = vad if vad and name == "silero_vad.onnx" else directory / name
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != sha:
                raise ValueError(f"empreinte différente : {path.name}")


def symbol(lib, name, restype, *args):
    f = getattr(lib, name)
    f.argtypes = args
    f.restype = restype
    return f


def load_audio(path):
    # Required by the locked manifest: little-endian 16-bit mono PCM at 16 kHz.
    import numpy as np
    with wave.open(str(path)) as stream:
        return np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32) / 32768



def build_segmenter(lib, vad, stack):
    create_gate = symbol(lib, "nv_silero_create", PTR, c.c_char_p)
    destroy_gate = symbol(lib, "nv_silero_destroy", None, PTR)
    reset = symbol(lib, "nv_silero_reset", None, PTR)
    accept = symbol(lib, "nv_silero_accept", c.c_int, PTR, PCM, c.c_size_t, EMIT, PTR)
    finish = symbol(lib, "nv_silero_finish", c.c_int, PTR, EMIT, PTR)
    gate = create_gate(str(vad.resolve(strict=True)).encode("utf-8"))
    if not gate:
        raise RuntimeError("impossible de charger Silero")
    stack.callback(destroy_gate, gate)

    def collect_segments(clip):
        import numpy as np
        results = []
        reset(gate)

        @EMIT
        def collect(_, pcm, count):
            results.append(np.ctypeslib.as_array(pcm, shape=(count,)).copy())
            return 0

        for index in range(0, clip.size, 1600):
            packet = clip[index:index + 1600]
            if accept(gate, packet.ctypes.data_as(PCM), packet.size, collect, None):
                raise RuntimeError("échec Silero")
        if finish(gate, collect, None):
            raise RuntimeError("échec Silero en fin de dictée")
        return results
    return collect_segments


def load_silero(binary, model, stack):
    if not binary or not model:
        raise ValueError("--binary and --pause-vad are required with --mode pause")
    binary = binary.resolve(strict=True)
    if os.name == "nt":
        stack.enter_context(os.add_dll_directory(str(binary.parent)))
    verify_pack(model.parent, {"silero_vad.onnx": ULTIMED_LOCK["silero_vad.onnx"]}, model)
    return build_segmenter(c.CDLL(str(binary)), model, stack)


def native_whisper(lib, args, stack):
    from p0.asr_compare import WHISPER_LOCK
    if not args.vad:
        raise ValueError("le pont Whisper requiert un modèle Silero GGML")
    verify_pack(args.model.parent, {args.model.name: WHISPER_LOCK.get(args.model.name)}, None)
    verify_pack(args.vad.parent, {args.vad.name: WHISPER_LOCK.get(args.vad.name)}, None)
    if args.pause_ms is None:
        create = symbol(lib, "NVWhisperCreate", PTR, c.c_char_p, c.c_char_p)
        create_args = ()
    else:
        create = symbol(lib, "NVWhisperCreateWithPause", PTR, c.c_char_p, c.c_char_p, c.c_uint32)
        create_args = (args.pause_ms,)
    destroy = symbol(lib, "NVWhisperDestroy", None, PTR)
    reset = symbol(lib, "NVWhisperReset", None, PTR)
    accept = symbol(lib, "NVWhisperAccept", c.c_int, PTR, PCM, c.c_size_t, WHISPER_EMIT, PTR)
    finish = symbol(lib, "NVWhisperFinish", c.c_int, PTR, WHISPER_EMIT, PTR)
    handle = create(str(args.model.resolve()).encode("utf-8"), str(args.vad.resolve()).encode("utf-8"), *create_args)
    if not handle:
        raise RuntimeError("impossible de charger le pont Whisper")
    stack.callback(destroy, handle)

    def run(path):
        clip = load_audio(path)
        now = perf_counter()
        pause, stop = [], []
        errors = []
        end = None
        target = pause
        reset(handle)

        @WHISPER_EMIT
        def collect(_, text, size, ms):
            try:
                target.append({"text": text.decode("utf-8"), "audio_ms": end, "sample_count": size, "decode_ms": ms})
            except (AttributeError, UnicodeError) as error:
                errors.append(error)
                return -1
            return 0

        for index in range(0, clip.size, 1600):
            packet = clip[index:index + 1600]
            end = (index + packet.size) // 16
            if accept(handle, packet.ctypes.data_as(PCM), packet.size, collect, None):
                raise RuntimeError(f"échec du pont Whisper après {end} ms ({path.name}, {errors})")
        end, target = None, stop
        if finish(handle, collect, None):
            raise RuntimeError(f"échec de la fin du pont Whisper ({path.name}, {errors})")
        return {"text": " ".join(r["text"] for r in pause + stop if r["text"]), "pause": pause, "stop": stop,
                "elapsed_ms": (perf_counter() - now) * 1000}
    return run

def engine_runner(args, stack):
    if not args.binary or not args.model:
        raise ValueError("--binary (library) and --model (directory) are required")
    binary = args.binary.resolve(strict=True)
    if os.name == "nt":
        stack.enter_context(os.add_dll_directory(str(binary.parent)))
    lib = c.CDLL(str(binary))
    if args.engine == "whisper-native":
        return native_whisper(lib, args, stack)
    directory = args.model.resolve(strict=True)
    model = str(directory).encode("utf-8")
    verify_pack(directory, ZIPFORMER_LOCK if args.engine == "zipformer" else ULTIMED_LOCK, args.vad)
    if args.engine == "zipformer":
        create = symbol(lib, "nv_zipformer_create", PTR, c.c_char_p, c.c_int32)
        destroy = symbol(lib, "nv_zipformer_destroy", None, PTR)
        decode = symbol(lib, "nv_zipformer_run", PTR, PTR, PCM, c.c_int32,
                        c.POINTER(c.c_int32), c.POINTER(c.c_double))
        release = symbol(lib, "nv_zipformer_free", None, PTR)
        handle = create(model, args.threads)
        if not handle:
            raise RuntimeError("impossible de charger Zipformer")
        stack.callback(destroy, handle)

        def run(path):
            clip = load_audio(path)
            first = c.c_int32()
            stop = c.c_double()
            now = perf_counter()
            ptr = decode(handle, clip.ctypes.data_as(PCM), clip.size, c.byref(first), c.byref(stop))
            wall = (perf_counter() - now) * 1000
            if not ptr:
                raise RuntimeError("échec du décodage Zipformer")
            try:
                text = c.string_at(ptr).decode("utf-8")
            finally:
                release(ptr)
            return {"text": text, "elapsed_ms": wall, "first_audio_ms": first.value if first.value >= 0 else None,
                    "flush_ms": stop.value}
        return run

    create = symbol(lib, "NVUltiMedCreate", PTR, c.c_char_p)
    destroy = symbol(lib, "NVUltiMedDestroy", None, PTR)
    release = symbol(lib, "NVUltiMedFreeText", None, PTR)
    decode = symbol(lib, "NVUltiMedDecode", c.c_int, PTR, PCM, c.c_int32, c.POINTER(PTR))
    handle = create(model)
    if not handle:
        raise RuntimeError("impossible de charger UltiMed")
    stack.callback(destroy, handle)
    split = build_segmenter(lib, args.vad or args.model / "silero_vad.onnx", stack)

    def run(path):
        import numpy as np
        clip = load_audio(path)
        now = perf_counter()
        results = split(clip)

        def infer(fragment):
            ptr = PTR()
            start = perf_counter()
            code = decode(handle, fragment.ctypes.data_as(PCM), fragment.size, c.byref(ptr))
            ms = (perf_counter() - start) * 1000
            if code or not ptr:
                raise RuntimeError("échec du décodage UltiMed")
            try:
                return {"text": c.string_at(ptr).decode("utf-8"), "decode_ms": ms}
            finally:
                release(ptr)

        size = 30 * 16000
        extended = []
        if args.mode == "extended" and results:
            if clip.size <= size:
                # Matched full reference on <=30s, preserving the original audio when speech was detected.
                extended = [clip]
            else:
                # Join adjacent qualified segments without changing their samples.
                # Never join over 30 s, and never cut within one segment.
                queue = []
                size_used = 0
                for part in results:
                    join_pad = 3200 if queue else 0
                    if queue and size_used + join_pad + part.size > size:
                        extended.append(np.concatenate(queue))
                        queue, size_used, join_pad = [], 0, 0
                    if join_pad:
                        queue.append(np.zeros(join_pad, dtype=np.float32))
                    queue.append(part)
                    size_used += join_pad + part.size
                if queue:
                    extended.append(np.concatenate(queue))
        segments = [infer(segment) for segment in (extended if args.mode == "extended" else results)]
        return {"text": " ".join(row["text"] for row in segments if row["text"]),
                "elapsed_ms": (perf_counter() - now) * 1000, "segments": segments}
    return run
