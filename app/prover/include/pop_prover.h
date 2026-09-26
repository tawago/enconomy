/* pop-prover: option A per-phone prover for POPT v2 (circuits oa2t_s48 / oa2t_s44).
 * Spartan2 (zkID fork d687dbb), Hyrax on T-256; circom C++ witness linked in.
 * All calls are blocking and heavy (seconds, ~2 GB): call from a background thread.
 * Return value: POP_OK or an error code; on error *err (if non-null) holds a UTF-8 message.
 * Every PopBuf filled by the library must be released with pop_buf_free. */
#ifndef POP_PROVER_H
#define POP_PROVER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    POP_OK = 0,
    POP_ERR_ARG = 1,     /* null / non UTF-8 / malformed argument, unknown key shape */
    POP_ERR_IO = 2,      /* key file missing or undecodable */
    POP_ERR_WITNESS = 3, /* circom witness generation failed (a circuit assert fired) */
    POP_ERR_UNSAT = 4,   /* witness does not satisfy the R1CS: no proof is produced */
    POP_ERR_PROVE = 5,
    POP_ERR_VERIFY = 6,
    POP_ERR_PANIC = 7
};

typedef struct PopBuf {
    uint8_t *ptr;
    size_t len;
} PopBuf;

typedef struct PopProver PopProver;

void pop_buf_free(PopBuf buf);
const char *pop_prover_version(void);

/* Load a proving key (bincode, from the pinned trusted setup). The circuit is identified from the key. */
int32_t pop_prover_open(const char *pk_path, PopProver **out, PopBuf *err);
void pop_prover_close(PopProver *p);
/* 48000 (oa2t_s48) or 44100 (oa2t_s44); 0 for NULL. */
uint32_t pop_prover_sample_rate(const PopProver *p);

/* Witness + check of every constraint, no proof. public_json (nullable) gets {"public": ["dec", ...]}. */
int32_t pop_prover_check(const PopProver *p, const uint8_t *input_json, size_t input_len,
                         PopBuf *public_json, PopBuf *err);
/* Witness -> constraint check -> proof bytes (~1.6 MB). Fails with POP_ERR_UNSAT instead of emitting a bad proof. */
int32_t pop_prover_prove(const PopProver *p, const uint8_t *input_json, size_t input_len,
                         PopBuf *proof, PopBuf *err);
/* open + prove + close. */
int32_t pop_prove(const char *pk_path, const uint8_t *input_json, size_t input_len, PopBuf *proof, PopBuf *err);

/* Host tests: verify with a vk file; expected_json (nullable) must equal the proof's public vector. */
int32_t pop_verify(const char *vk_path, const uint8_t *proof, size_t proof_len,
                   const uint8_t *expected_json, size_t expected_len, PopBuf *public_json, PopBuf *err);

#ifdef __cplusplus
}
#endif

#endif
