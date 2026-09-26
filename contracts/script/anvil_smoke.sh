#!/usr/bin/env bash
# End-to-end smoke on an anvil fork of Ethereum Sepolia: deploy -> create Safe -> presence spend ->
# forced revert (guardians, no presence) -> hatch setGuard(0). Test keys only.
#   anvil --fork-url <sepolia rpc> --hardfork osaka --port 8612 --silent &
#   RPC=http://127.0.0.1:8612 script/anvil_smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."
RPC=${RPC:-http://127.0.0.1:8612}
[ "$(cast chain-id --rpc-url "$RPC")" = 11155111 ] || { echo "need an anvil fork of sepolia at $RPC" >&2; exit 1; }
# anvil default accounts 0..2 (public test keys)
K0=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
export G1_PK=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
export G2_PK=0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a
PHA=0xA1 PHB=0xB1 ISS=0xC0FFEE BOB=0x000000000000000000000000000000000000b0b0
PY="uv run --quiet --with cryptography python3 script/pop_sigs.py"
export DEPLOY_OUT=deployments/anvil-11155111.json PRIVATE_KEY=$K0

forge script script/Deploy.s.sol --rpc-url "$RPC" --broadcast --silent
export GUARD=$(jq -r .PopSafeGuard $DEPLOY_OUT) SETUP=$(jq -r .PopSafeSetup $DEPLOY_OUT) OWNER_FACTORY=$(jq -r .P256OwnerFactory $DEPLOY_OUT)
IPUB=$($PY pub $ISS)
export PUB_A=$($PY pub $PHA) PUB_B=$($PY pub $PHB) ISSUER_X=0x${IPUB:4:64} ISSUER_Y=0x${IPUB:68:64} \
  GUARDIAN_1=$(cast wallet address --private-key $G1_PK) GUARDIAN_2=$(cast wallet address --private-key $G2_PK) \
  DELAY=300 GRACE=600 SALT=$(date +%s)
OUT=$(forge script script/CreatePopSafe.s.sol --rpc-url "$RPC" --broadcast)
SAFE=$(echo "$OUT" | awk '/ safe 0x/{print $2}' | tr 'A-F' 'a-f'); OA=$(echo "$OUT" | awk '/ ownerA /{print $2}'); OB=$(echo "$OUT" | awk '/ ownerB /{print $2}')
echo "safe $SAFE guard $GUARD"
[ "$(cast call $SAFE 'getThreshold()(uint256)' --rpc-url $RPC)" = 2 ]
[ "$(cast storage $SAFE 0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8 --rpc-url $RPC | cast parse-bytes32-address)" = "$(cast to-check-sum-address $GUARD)" ]
[ "$(cast storage $SAFE 0x6c9a6c4a39284e37ed1cf53d337577d14212a4870fb976a4366c693b939918d5 --rpc-url $RPC)" = 0x0000000000000000000000000000000000000000000000000000000000000000 ]
cast send $SAFE --value 0.01ether --rpc-url $RPC --private-key $K0 >/dev/null

# 1. presence spend
N=$(cast call $SAFE 'nonce()(uint256)' --rpc-url $RPC)
H=$(cast call $SAFE 'getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)' $BOB 1000000000000000 0x 0 0 0 0 0x0000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000 $N --rpc-url $RPC)
TS=$(cast block latest -f timestamp --rpc-url $RPC)
SIGS=$($PY sigs --h $H --safe $SAFE --chain 11155111 --owner-a $OA --key-a $PHA --owner-b $OB --key-b $PHB --issuer $ISS --expiry $((TS + 900)))
EXEC='execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)'
R=$(cast send $SAFE "$EXEC" $BOB 1000000000000000 0x 0 0 0 0 0x0000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000 $SIGS --rpc-url $RPC --private-key $K0 --json)
echo "spend: status $(echo $R | jq -r .status) gasUsed $(cast to-dec $(echo $R | jq -r .gasUsed)) bob $(cast balance $BOB --rpc-url $RPC)"
[ "$(echo $R | jq -r .status)" = 0x1 ]

# 2. forced revert: guardians sign a spend, no presence -> NoPresence (0x$(cast sig 'NoPresence()'))
N=$(cast call $SAFE 'nonce()(uint256)' --rpc-url $RPC)
H=$(cast call $SAFE 'getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)' $BOB 1000000000000000 0x 0 0 0 0 0x0000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000 $N --rpc-url $RPC)
S1=$(cast wallet sign --no-hash $H --private-key $G1_PK); S2=$(cast wallet sign --no-hash $H --private-key $G2_PK)
if [[ "$(echo $GUARDIAN_1 | tr A-F a-f)" < "$(echo $GUARDIAN_2 | tr A-F a-f)" ]]; then GS=$S1${S2:2}; else GS=$S2${S1:2}; fi
E=$(cast call $SAFE "$EXEC" $BOB 1000000000000000 0x 0 0 0 0 0x0000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000 $GS --rpc-url $RPC 2>&1 || true)
echo "forced revert: $E" | head -c 300; echo
echo "$E" | grep -q "$(cast sig 'NoPresence()')" || echo "$E" | grep -q NoPresence

# 3. hatch: announce setGuard(0), wait delay, execute with G1+G2
export SAFE TO=$SAFE DATA=$(cast calldata 'setGuard(address)' 0x0000000000000000000000000000000000000000) NONCE=$N
MODE=announce forge script script/Recover.s.sol --rpc-url "$RPC" --broadcast --silent
cast rpc evm_increaseTime 301 --rpc-url $RPC >/dev/null && cast rpc evm_mine --rpc-url $RPC >/dev/null
MODE=exec forge script script/Recover.s.sol --rpc-url "$RPC" --broadcast --silent
G=$(cast storage $SAFE 0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8 --rpc-url $RPC)
echo "hatch: guard slot $G"
[ "$G" = 0x0000000000000000000000000000000000000000000000000000000000000000 ]
echo "SMOKE OK"
