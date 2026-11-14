#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// One serial caller. All models remain local and resident until Destroy.
void* NVWhisperCreate(const char* model_utf8, const char* vad_utf8);
// Benchmarkable pause: 96..3000 ms, rounded up to the next 32 ms VAD frame.
void* NVWhisperCreateWithPause(const char* model_utf8, const char* vad_utf8, unsigned pause_ms);
void NVWhisperDestroy(void* handle);
void NVWhisperReset(void* handle);
typedef int (*NVWhisperEmit)(void* context, const char* text, size_t audio_samples, double decode_ms);
typedef int (*NVWhisperCancelled)(void* context);
void NVWhisperSetCancellation(void* handle, NVWhisperCancelled callback, void* context);
int NVWhisperAccept(void* handle, const float* samples, size_t count, NVWhisperEmit emit, void* context);
int NVWhisperFinish(void* handle, NVWhisperEmit emit, void* context);
#ifdef __cplusplus
}
#endif
