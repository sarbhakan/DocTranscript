#ifndef NOTE_VIVE_ULTIMED_BRIDGE_H
#define NOTE_VIVE_ULTIMED_BRIDGE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* One caller at a time per handle. Create returns NULL if model loading fails. */
void *NVUltiMedCreate(const char *model_directory);

/* Replaces the hints for subsequent calls. UTF-8 phrases separated by LF;
 * NULL or empty disables hints. Returns the accepted count or -1 on error. */
int NVUltiMedSetPhrases(void *handle, const char *terms);

/* Mono Float32 PCM at 16 kHz. 0 on success, including an empty transcript.
 * On success the caller owns *out_text; on failure it is NULL. */
int NVUltiMedDecode(void *handle, const float *samples, int32_t sample_count, char **out_text);
void NVUltiMedFreeText(char *text);
void NVUltiMedDestroy(void *handle);

#ifdef __cplusplus
}
#endif

#endif
