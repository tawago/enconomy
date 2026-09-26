/* zkprove C ABI (src/ffi.rs). UltraHonk, bb 5.0.0-nightly.20260522, evm target (keccak, ZK).
   proof / public_inputs = exact bytes of `bb prove -t evm` output files. Free every ZkBuf with zk_buf_free.
   Codes: 0 ok, 1 bad argument, 2 io, 3 prove failed, 4 witness failed, 9 panic. */
#pragma once
#include <stddef.h>
#include <stdint.h>
typedef struct { uint8_t *ptr; size_t len; } ZkBuf;
const char *zk_version(void);
void zk_buf_free(ZkBuf b);
/* whole thing on device: ACVM witness from Prover.toml text, then prove (built with --features witness) */
int zk_prove(const char *circuit_json_path, const uint8_t *inputs_toml, size_t inputs_len, const char *crs_path,
             const char *vk_path /* nullable */, ZkBuf *proof, ZkBuf *public_inputs, ZkBuf *err);
/* prove from a nargo-made witness (gzipped WitnessStack, target/<name>.gz) */
int zk_prove_witness(const char *circuit_json_path, const uint8_t *witness_gz, size_t witness_len, const char *crs_path,
                     const char *vk_path /* nullable */, ZkBuf *proof, ZkBuf *public_inputs, ZkBuf *err);
