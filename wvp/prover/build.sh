#!/bin/bash
# Builds into $WVP_THIRD_PARTY. Run prover/fetch.sh source first. Usage: prover/build.sh witness | cached | threads | plain
#   witness: jwt_1k.wasm, with circom 2.1.8. The pinned repo asks for 2.2.3, so a throwaway copy has its pragma rewritten.
#   cached:  fast wrapper, one thread. The site servers use it.
#   threads: fast wrapper with wasm atomics. The extension uses it. Needs std rebuilt with atomics: RUSTC_BOOTSTRAP + -Zbuild-std.
#   plain:   the first wrapper, one thread, no kept keys. Nothing in the demo loads it.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
: "${WVP_THIRD_PARTY:?Set WVP_THIRD_PARTY. See prover/README.md.}"
T=$WVP_THIRD_PARTY
export CARGO_INCREMENTAL=0

witness() {
  local WORK=$T/circuits218 DEPS=$T/npmdeps/node_modules
  mkdir -p "$DEPS/@zk-email" "$WORK"
  [ -d "$DEPS/circomlib" ] || (cd "$T/npmdeps" && npm pack circomlib@2.0.5 --ignore-scripts && mkdir "$DEPS/circomlib" && tar xzf circomlib-2.0.5.tgz --strip-components 1 -C "$DEPS/circomlib")
  [ -d "$DEPS/@zk-email/circuits" ] || (cd "$T/npmdeps" && npm pack @zk-email/circuits@6.3.4 --ignore-scripts && mkdir "$DEPS/@zk-email/circuits" && tar xzf zk-email-circuits-6.3.4.tgz --strip-components 1 -C "$DEPS/@zk-email/circuits")
  if [ ! -d "$WORK/circuits" ]; then
    cp -R "$T/zkID/wallet-unit-poc/circom/circuits" "$WORK/circuits"
    find "$WORK/circuits" -name '*.circom' -exec perl -pi -e 's/pragma circom 2\.\d+\.\d+;/pragma circom 2.1.8;/' {} +
  fi
  ln -sfn "$DEPS" "$WORK/node_modules"
  mkdir -p "$WORK/build/jwt_1k"
  circom --version
  circom "$WORK/circuits/main/jwt_1k.circom" -o "$WORK/build/jwt_1k" --r1cs --sym --wasm --O2 --prime secq256r1 -l "$DEPS"
  cp "$WORK/build/jwt_1k/jwt_1k_js/jwt_1k.wasm" "$T/sdk-q1/assets/jwt_1k.wasm"
  shasum -a 256 "$T/sdk-q1/assets/jwt_1k.wasm"
}

fast() { # cached | threads
  local MODE=$1 OUT=$T/p2-$1
  mkdir -p "$OUT"
  export CARGO_TARGET_DIR=$T/target-p2-$MODE
  cd "$HERE/fast"
  if [ "$MODE" = cached ]; then
    cargo +1.92.0 build --release --locked --target wasm32-unknown-unknown
  else
    export RUSTC_BOOTSTRAP=1
    export RUSTFLAGS="-C target-feature=+atomics,+bulk-memory,+mutable-globals -C link-arg=--shared-memory -C link-arg=--import-memory -C link-arg=--max-memory=4294967296 -C link-arg=--export=__stack_pointer -C link-arg=--export=__wasm_init_tls -C link-arg=--export=__tls_size -C link-arg=--export=__tls_align -C link-arg=--export=__tls_base -C link-arg=-zstack-size=2097152"
    cargo +1.92.0 build --release --locked --target wasm32-unknown-unknown -Zbuild-std=std,panic_abort
  fi
  cp "$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/openac_plain2.wasm" "$OUT/openac_plain2.wasm"
  shasum -a 256 "$OUT/openac_plain2.wasm"
}

plain() {
  export CARGO_TARGET_DIR=$T/target-plain
  cd "$HERE/plain"
  cargo +1.92.0 build --release --locked --target wasm32-unknown-unknown
  cp "$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/openac_plain.wasm" "$T/openac_plain.wasm"
  shasum -a 256 "$T/openac_plain.wasm"
}

case "$1" in
  witness) witness ;;
  cached|threads) fast "$1" ;;
  plain) plain ;;
  *) echo "Usage: prover/build.sh witness | cached | threads | plain"; exit 2 ;;
esac
