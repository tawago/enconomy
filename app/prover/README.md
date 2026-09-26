# pop-prover (option A per-phone prover)

Rust crate with a C ABI (plus JNI on Android) that proves one phone's POPT v2 transcript with the
`oa2t_s48` / `oa2t_s44` circuits. Port of `research/sound-bound/spikes/zk/optionA-v2/prover` (`oa2zk`):
circom C++ witness via witnesscalc-adapter (zkmopro, rev e5a82bcb), zkID Spartan2 fork (rev d687dbb,
`zk_spartan::R1CSSNARK<T256HyraxEngine>`), same pins as the spike. mopro not used: three calls don't
need its bindings generator.

What changed vs the spike binary:
- No `.r1cs` at runtime (400 MB). The proving key already holds the R1CS shape; synthesis only allocates
  the circom variables (Spartan2's `SatisfyingAssignment` ignores constraints). The circuit is identified
  from the key's public-input count (48011 = s48, 44111 = s44).
- `check` runs first, always: witness -> `A·z ∘ B·z == C·z` over every constraint of the key's shape ->
  prove. The spike prover proves any witness and the proof then fails verification. Tampered fixtures
  (`_t-half`, `_t-nonce`, `_t-resign_*`) pass witness generation and are only caught here.
- Keys load plain (mmap) or zstd-compressed (streamed, never written out inflated).
- GMP x18 fix built in (`build.rs`), never touching the spike: host macOS links Homebrew GMP 6.3.0
  (same as spike `fix_gmp.sh`), Android GMP is configured `--disable-assembly`, iOS already is.

Honest scope: a valid proof says a credentialed device ran the integer arrival rule on a capture it
committed to. It does not say two people were there (REVIEW F3/F4 of the spike).

## Files

- `src/lib.rs` `Prover::{load, witness, check, prove}`, `Verifier::{load, verify}`
- `src/ffi.rs` C ABI, header `include/pop_prover.h` (+ `module.modulemap` for Swift)
- `src/jni_android.rs` `com.enconomy.pop.zk.PopProverNative` (`open/close/sampleRate/check/prove`)
- `src/bin/popprover.rs` host CLI: `check`, `prove`, `verify`, `e2e`, `corrupt`
- `scripts/sync_circuits.sh` copy `oa2t_s48/s44 .cpp/.dat` from the spike into `cpp/` (gitignored, 25 MB)
- `scripts/build_android.sh`, `scripts/build_ios.sh`, `scripts/host_e2e.sh`

Gitignored: `target/ cpp/ dist/ keys/ *.pk *.vk *.zst *.proof`.

## Build

Everything heavy goes through the machine lock (`H=../../research/sound-bound/spikes/zk/tools/heavy.sh`).
First build of each target clones witnesscalc (pinned 707dc54 / d0e66a5) and builds GMP; needs network
(`POP_WITNESSCALC_GIT`, `POP_GMP_TARBALL` for offline mirrors).

```
scripts/sync_circuits.sh
$H prover-host    cargo build --release && cargo test --release
$H prover-e2e     scripts/host_e2e.sh                  # real fixtures, needs the spike keys
$H prover-android scripts/build_android.sh             # dist/android/arm64-v8a/libpop_prover.so
$H prover-ios     scripts/build_ios.sh                 # dist/ios/PopProver.xcframework
```

Android: `ANDROID_NDK` defaults to `~/Library/Android/sdk/ndk/28.2.13676358`, API 24 (app minSdk),
cargo-ndk. The `.so` needs only libc/libm/libdl (libc++ static). Drop it in `jniLibs/arm64-v8a/`.
iOS: device + simulator (arm64) static libs in one xcframework; link `-lc++`. Objects target iOS 16.0
(`IPHONEOS_DEPLOYMENT_TARGET`; `build.rs` builds GMP without it, since it retargets the host clang
GMP's configure uses for build tools).

| Artifact | Size |
| --- | ---: |
| host `popprover` (macOS arm64) | 23.4 MB |
| `libpop_prover.so` (android arm64, stripped of debuginfo) | 24.5 MB |
| `libpop_prover.a` (ios arm64; a linked test binary is 29 MB) | 56.2 MB |
| `libpop_prover.a` (ios-sim arm64) | 48.6 MB |
| of which embedded circuit `.dat` | 10.3 + 9.7 MB |
| `oa2t_s48.pk` / `.pk.zst` (zstd -3) | 470 MB / 11.7 MB |
| `oa2t_s44.pk` / `.pk.zst` | 449 MB / 11.3 MB |
| proof | 1.65 MB (s48), 1.52 MB (s44) |

## Measured (M2, 8 GB, shared machine)

`popprover e2e`, fixture 180ca04b (fresh process, pk load + prove, then vk load + verify):

| circuit | pk load | witness | check | prove | verify (+vk load) | peak footprint |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| s48 (48k A) | 1.0–3.1 s | 0.37 s | 0.13 s | 2.2–3.7 s | 2.2–2.4 s (+0.8–3.1 s) | 1.90 GB |
| s44 (mix B) | 4.2 s | 0.34 s | 0.15 s | 2.3 s | 2.2 s (+2.0 s) | 1.87 GB |

Loading the `.zst` key: 1.0 s vs 1.1 s for the plain file, same peak.
iOS simulator (iPhone 16 Pro, iOS 18.3, C ABI test program linked against the xcframework, `.zst` key):
tampered input refused with `POP_ERR_UNSAT`, fixture proved and verified (open 15 s, prove 36 s,
verify 33 s: the Mac was swapping with the simulator up; not a device number). The check adds ~0.13 s.
halfCommit for 180ca04b_48k_A = `1108569989…322080`, same as the spike. The spike's `oa2zk verify`
accepts proofs from this crate (same bincode `R1CSSNARK`).

## C API

```
PopProver *p; PopBuf err = {0}, proof = {0};
if (pop_prover_open("<files>/zk/oa2t_s48.pk.zst", &p, &err) != POP_OK) ...
int rc = pop_prover_prove(p, json, json_len, &proof, &err);   // POP_ERR_UNSAT: no proof
pop_buf_free(proof); pop_prover_close(p);
```
Input JSON: the witness input of `prep_popt2.py` (spec `zk-port-spec.md` §5.3). Keep the handle open
only while proving (~1.5 GB resident). Call off the main thread. The witness runs on its own 512 MB
stack thread (spike saw segfaults on 8 MB).

## Proving key handling

Decision: **download on first use from the server, zstd-compressed, sha256-pinned in the app, cached in
the app files dir, resumable.**

- Server: `GET /v1/zk/keys/{circuit}.pk.zst` (static file, Range support) from a gitignored dir
  (`POP_ZK_KEYS`), 11–12 MB each. The pk is public; soundness rests on the server's pinned vk.
- App: pins `sha256(pk.zst)` per circuit at build time (manifest next to the vk pins; current setup:
  s48 `49b6ed65…d045`, s44 `136ddb87…f8d1` for `zstd -3` of spike keys with pk sha256 `43d71d02…e269` /
  `c60d5dea…9db`; the server pins vk `488e44c9…5a3d` / `7c5cb18c…e4e0`). A new setup means new pins in
  both places, same release.
- Fetch only the circuit for the phone's rate (Android: nearly always 48000). Prefetch after enrollment on
  Wi-Fi; the first v2 run waits for it or falls back to v1.
- Resumable: write `zk/<circuit>.pk.zst.part`, `Range: bytes=<size>-` on retry, hash on completion,
  atomic rename. Hash mismatch -> delete and refetch once, then fail to v1.
- The prover reads the `.zst` directly; nothing is inflated to disk (12 MB on disk, not 470 MB).
- Android: `filesDir/zk/`. iOS: `Application Support/zk/`, excluded from backup. Big RAM: iOS needs
  `com.apple.developer.kernel.increased-memory-limit`; Android allocates natively (not Java heap).

Alternatives considered:
- Bundle in APK/IPA: 23 MB compressed for both rates is feasible now, but ties every trusted-setup change
  to an app release and bloats installs that only need one rate. Kept as fallback if the demo network is
  bad.
- Uncompressed download (470 MB): no reason once zstd gets 40x (the key is mostly sparse matrix indices).
- Play Asset Delivery / iOS On-Demand Resources: store-only, not for sideloaded demo builds.
- Setup on the phone from the `.r1cs`: needs the 400 MB r1cs anyway plus ~2 GB and must reproduce the
  server's vk exactly; no gain.
- Dev shortcut: `adb push` / Xcode file copy into the same path, same hash check.

## Not done here

- Kotlin/Swift callers, download code, server key endpoint (other chunks).
- No run on a real phone yet: device RAM/time unknown (estimate iPhone ~3 s, Pixel 7–10 s, ~2 GB).
  Android GMP without asm is slower; the witness is ~0.4 s of the total on the Mac.
- `oa2t_pair` is not in this crate (the server proves the pair, spec §5.3).
