#ifndef NOTEVIVE_SILERO_PAUSE_H
#define NOTEVIVE_SILERO_PAUSE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NV_SILERO_PAUSE_MS 576
#define NV_SILERO_PREROLL_MS 256
#define NV_SILERO_MAX_SEGMENT_MS 30000

// The returned handle belongs to one serial queue. The model is Silero VAD 6.2.
void *nv_silero_create(const char *model_path);
void nv_silero_destroy(void *vad);
void nv_silero_reset(void *vad);

// A completed segment is valid only during this synchronous callback. Return
// zero to continue or nonzero to interrupt. A packet can complete multiple
// segments. The input to both the VAD and callbacks is mono PCM float at 16 kHz.
typedef int (*NVSileroEmit)(void *context, const float *pcm16k, size_t count);

// Return zero on success, -1 on failure. Reset after a failed call. finish()
// processes any final partial input block and emits a qualified last segment.
int nv_silero_accept(void *vad, const float *pcm16k, size_t count, NVSileroEmit emit, void *context);
int nv_silero_finish(void *vad, NVSileroEmit emit, void *context);

#ifdef __cplusplus
}
#endif
#endif
