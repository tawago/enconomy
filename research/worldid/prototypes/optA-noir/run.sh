#!/bin/bash
# Option A in Noir: build, real-fixture witness, prove, verify, Solidity gas. Heavy steps go through heavy.sh.
# usage: run.sh [FIXTURE] [ROLE]      (default 180ca04b_48k A)
# Build outputs live in $S (scratchpad), sources stay here.
set -e
FX=${1:-180ca04b_48k}; ROLE=${2:-A}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../.." && pwd)
S=${S:-/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/optA}
BIN=${BIN:-/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/onchain-zk/opt3-nonnative-p256/bin}
H=$ROOT/research/sound-bound/spikes/zk/tools/heavy.sh
PY=${PY:-python3}   # needs numpy + soundfile (the old research/proximity-echo/.venv is gone)
B=$S/noir; mkdir -p $B $S/logs
rsync -a --exclude target "$HERE/noir/" "$B/"

# 1. compile (phone ~1 min, ~2.3 GB) + gate counts
for p in phone phone_pub pair helper phone_opt phone_opt_popc phone_popc; do
  (cd $B/$p && $H optA-compile-$p /usr/bin/time -l $BIN/nargo compile) > $S/logs/compile_$p.log 2>&1
  [ $p = helper ] || echo "$p $($BIN/bb gates -b $B/$p/target/$p.json | tr -d ' \n')"
done

# 2. real witness: capture regenerated from the field WAV, Poseidon2 tree/code commitment, SE re-signature
NARGO=$BIN/nargo $PY "$HERE/gen_inputs.py" $FX $ROLE $B
(cd $B/phone && /usr/bin/time -l $BIN/nargo execute phone) > $S/logs/exec_phone.log 2>&1
(cd $B/pair && $BIN/nargo execute pair) > $S/logs/exec_pair.log 2>&1
for p in phone_opt phone_opt_popc; do (cd $B/$p && $BIN/nargo execute $p) > $S/logs/exec_$p.log 2>&1; done

# 3. vk, prove (peak RSS via time -l), verify, Solidity verifier (EVM target: keccak transcript, ZK)
for p in phone pair phone_opt; do
  cd $B/$p; mkdir -p vk out
  $BIN/bb write_vk -b target/$p.json -o vk -t evm
  $H optA-prove-$p /usr/bin/time -l $BIN/bb prove -b target/$p.json -w target/$p.gz -k vk/vk -o out -t evm > $S/logs/prove_$p.log 2>&1
  egrep "real|maximum resident|peak memory" $S/logs/prove_$p.log
  $BIN/bb verify -k vk/vk -p out/proof -i out/public_inputs -t evm
  $BIN/bb write_solidity_verifier -k vk/vk -o Verifier.sol -t evm
done
sed 's/^contract HonkVerifier is/contract PhoneVerifier is/' $B/phone/Verifier.sol > "$HERE/forge/src/PhoneVerifier.sol"
sed 's/^contract HonkVerifier is/contract PairVerifier is/' $B/pair/Verifier.sol > "$HERE/forge/src/PairVerifier.sol"

# 4. gas: execution (forge, gasleft) and tx (anvil, incl. calldata)
cd "$HERE/forge"
RDIR=$B/phone/out PDIR=$B/pair/out forge test --no-match-contract GasPubTest -vv
(anvil --port 8622 --hardfork prague --gas-limit 100000000 > $S/logs/anvil.log 2>&1 &); sleep 3
../gas.sh PhoneVerifier $B/phone/out; ../gas.sh PairVerifier $B/pair/out
pkill -f "anvil --port 8622"

# 5. tampers (expect every case rejected by nargo execute)
NARGO=$BIN/nargo python3 "$HERE/tamper.py" $B $ROLE
