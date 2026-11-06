# Prover: how to get the third-party files

**Untested as a whole.** `fetch.sh` and `build.sh` have not been run end to end from a clean folder. The builds that produced our numbers came from the same sources, and rebuilt hashes may differ.

This repo holds only our own wrapper and SDK patch. zkID, the keys and every binary stay out. You put them in one folder and point `WVP_THIRD_PARTY` at it.

Pinned: `privacy-ethereum/zkID` at `b395e09c225ff45b003f0087c28e2e208e22f944`.

The folder must end up holding:

| Path | What | Used by |
|---|---|---|
| `keys/1k_*_proving.key` | Published keys, about 280 MB | Key host, then the extension |
| `keys/1k_*_verifying.key` | Published keys, about 280 MB | Site servers |
| `sdk-q1/` | zkID's SDK with `sdk-q1.patch`, built, with `node_modules` | Site servers, extension build |
| `sdk-q1/assets/jwt_1k.wasm` | Witness circuit you compile | Extension |
| `sdk-q1/assets/show.wasm` | Witness circuit, committed in zkID | Extension |
| `p2-threads/openac_plain2.wasm` | Threaded prover | Extension |
| `p2-cached/openac_plain2.wasm` | One-thread prover | Site servers |

## Steps

Needs: git, Node 24, Rust through rustup, circom 2.1.8.

```sh
export WVP_THIRD_PARTY=/path/to/empty/folder
rustup toolchain install 1.92.0 --profile minimal --target wasm32-unknown-unknown
rustup component add rust-src --toolchain 1.92.0

prover/fetch.sh source     # zkID at the pin, patched SDK, built. Also links prover/zkID, which Cargo needs.
prover/fetch.sh keys       # Downloads the 4 keys, checks digests.
prover/build.sh witness    # About 34 s and 1.57 GiB on an M2.
prover/build.sh cached
prover/build.sh threads
```

If the clone stalls, retry. One stalled here at 9 MB.

**State of these scripts.** They come from the commands used for the real build. The `fetch.sh source` steps were run from this folder, and the SDK source and `dist/index.js` matched what ran, byte for byte. `fetch.sh keys` and all of `build.sh` weren't rerun from here, only `cargo metadata --locked` on both crates. The binaries the demo was checked with came from the original build.

## What's here

- `fast/`: the wrapper that ran. It calls the same prover functions as upstream's wasm wrapper, without wasm-bindgen. It keeps decoded keys in memory, records step timings, and runs a rayon pool on Web Workers when built with atomics. No Spartan2 or `ecdsa-spartan2` source changes.
- `plain/`: the first wrapper, with its JS loader. One thread, keys decoded per call. Only the Node numbers in `../README.md` used it. Nothing in the demo loads it.
- `shims/`: small stand-ins for `getrandom` and `web-time`, which otherwise need wasm-bindgen. Randomness is still `crypto.getRandomValues`.
- `sdk-q1.patch`: lets `present()` take a ready signature in place of a raw device key, so K can stay unreadable. It's the only SDK change. Patched pin matches the SDK source that ran, file for file.
- `Cargo.lock` in each crate: pins Spartan2 and the rest. Upstream's lockfile, with wasm-bindgen entries dropped and the two shims added.

## Why the build isn't stock

Installing wasm-bindgen-cli and circom 2.2.3, and taking the prebuilt `openac-sdk@5.0.0`, were all denied on the build machine. So nobody ran stock OpenAC. `jwt_1k.wasm` is built with circom 2.1.8, not the 2.2.3 the repo asks for. Evidence it matches: two signal offsets in the `.sym` file equal the SDK's table, and proofs verify under the published keys. Against it: a 2.1.8 compile of `show` has a different hash from the committed one. So the compilers don't give identical output, and the demo uses the committed `show.wasm`.

The threaded build uses `RUSTC_BOOTSTRAP=1` and `-Zbuild-std`, on stable Rust 1.92.0.

## Hashes of what ran

SHA-256, first 16 hex. A rebuild may differ, since paths can end up in the binary. Not tested.

| Hash | File |
|---|---|
| `9172e7d7f6d37ab2` | `p2-threads/openac_plain2.wasm` |
| `7523039fdcd4b7f3` | `p2-cached/openac_plain2.wasm` |
| `f26032fc220e2bec` | `openac_plain.wasm` |
| `c02445452ee66124` | `sdk-q1/assets/jwt_1k.wasm` |
| `c08ba67b771688c5` | `sdk-q1/assets/show.wasm` |
