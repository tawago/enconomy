#!/usr/bin/env bash
# Sepolia demo: deploy (attestation verifier) -> create the 2-of-4 PoP Safe -> fund -> presence spend ->
# guardian spend with no presence, sent on purpose so it mines as a reverted tx (NoPresence).
# Keys (all gitignored): deployer = $SAFE_KEY_FILE (contracts/.env), phones + dev issuer = .env.demo,
# guardians = .env.guardians. Dry run: RPC=http://127.0.0.1:8612 OUT_TAG=anvil-11155111 script/sepolia_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; source .env.demo; source .env.guardians; set +a
RPC=${RPC:-${ETH_RPC:-https://ethereum-sepolia-rpc.publicnode.com}}
TAG=${OUT_TAG:-11155111}
[ "$(cast chain-id --rpc-url "$RPC")" = 11155111 ] || { echo "not sepolia" >&2; exit 1; }
pgrep -f "ens.sh" >/dev/null && { echo "ens.sh running, shared key: wait" >&2; exit 1; }
KF=${SAFE_KEY_FILE/#\~/$HOME}
export PRIVATE_KEY=0x$(tr -d '\n' <"$KF" | sed 's/^0x//')
DEP=$(cast wallet address --private-key "$PRIVATE_KEY")
PY="uv run --quiet --with cryptography python3 script/pop_sigs.py"
Z=0x0000000000000000000000000000000000000000
BOB=${BOB:-0x000000000000000000000000000000000000b0b0}
LOG=deployments/demo-$TAG.json
export DEPLOY_OUT=deployments/$TAG.json

if [ ! -s "$DEPLOY_OUT" ]; then
  forge script script/Deploy.s.sol --rpc-url "$RPC" --broadcast --slow
fi
export GUARD=$(jq -r .PopSafeGuard $DEPLOY_OUT) SETUP=$(jq -r .PopSafeSetup $DEPLOY_OUT) OWNER_FACTORY=$(jq -r .P256OwnerFactory $DEPLOY_OUT)
IPUB=$($PY pub $ISSUER_KEY)
export PUB_A=$($PY pub $PHONE_A_KEY) PUB_B=$($PY pub $PHONE_B_KEY) ISSUER_X=0x${IPUB:4:64} ISSUER_Y=0x${IPUB:68:64} \
  GUARDIAN_1=$(cast wallet address --private-key $G1_PK) GUARDIAN_2=$(cast wallet address --private-key $G2_PK) \
  DELAY=300 GRACE=600 SALT=${SALT:-1}
OUT=$(forge script script/CreatePopSafe.s.sol --rpc-url "$RPC" --broadcast --slow)
SAFE=$(echo "$OUT" | awk '/ safe 0x/{print $2}'); OA=$(echo "$OUT" | awk '/ ownerA /{print $2}'); OB=$(echo "$OUT" | awk '/ ownerB /{print $2}')
CREATE_TX=$(jq -r '[.transactions[].hash]|join(",")' broadcast/CreatePopSafe.s.sol/11155111/run-latest.json)
echo "safe $SAFE ownerA $OA ownerB $OB guard $GUARD"
[ "$(cast call $SAFE 'getThreshold()(uint256)' --rpc-url $RPC)" = 2 ]
[ "$(cast storage $SAFE 0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8 --rpc-url $RPC | cast parse-bytes32-address)" = "$(cast to-check-sum-address $GUARD)" ]
FUND_TX=$(cast send $SAFE --value 0.002ether --rpc-url $RPC --private-key "$PRIVATE_KEY" --json | jq -r .transactionHash)

EXEC='execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)'
HASHF='getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)'
V=500000000000000 # 0.0005 ETH

# 1. presence spend (phones A+B sign, dev issuer attests pop-safe-v2)
N=$(cast call $SAFE 'nonce()(uint256)' --rpc-url $RPC)
H=$(cast call $SAFE "$HASHF" $BOB $V 0x 0 0 0 0 $Z $Z $N --rpc-url $RPC)
TS=$(cast block latest -f timestamp --rpc-url $RPC)
SIGS=$($PY sigs --h $H --safe $SAFE --chain 11155111 --owner-a $OA --key-a $PHONE_A_KEY --owner-b $OB --key-b $PHONE_B_KEY --issuer $ISSUER_KEY --expiry $((TS + 900)))
R=$(cast send $SAFE "$EXEC" $BOB $V 0x 0 0 0 0 $Z $Z $SIGS --rpc-url $RPC --private-key "$PRIVATE_KEY" --json)
OK_TX=$(echo $R | jq -r .transactionHash); OK_GAS=$(cast to-dec $(echo $R | jq -r .gasUsed))
echo "spend: status $(echo $R | jq -r .status) gas $OK_GAS tx $OK_TX"
[ "$(echo $R | jq -r .status)" = 0x1 ]

# 2. guardians sign the same kind of spend with no presence: must revert NoPresence. Fixed gas limit so it mines.
N=$(cast call $SAFE 'nonce()(uint256)' --rpc-url $RPC)
H=$(cast call $SAFE "$HASHF" $BOB $V 0x 0 0 0 0 $Z $Z $N --rpc-url $RPC)
S1=$(cast wallet sign --no-hash $H --private-key $G1_PK); S2=$(cast wallet sign --no-hash $H --private-key $G2_PK)
if [[ "$(echo $GUARDIAN_1 | tr A-F a-f)" < "$(echo $GUARDIAN_2 | tr A-F a-f)" ]]; then GS=$S1${S2:2}; else GS=$S2${S1:2}; fi
E=$(cast call $SAFE "$EXEC" $BOB $V 0x 0 0 0 0 $Z $Z $GS --rpc-url $RPC 2>&1 || true)
echo "$E" | grep -q "$(cast sig 'NoPresence()')" || echo "$E" | grep -q NoPresence || { echo "expected NoPresence: $E" >&2; exit 1; }
R=$(cast send $SAFE "$EXEC" $BOB $V 0x 0 0 0 0 $Z $Z $GS --gas-limit 200000 --rpc-url $RPC --private-key "$PRIVATE_KEY" --json || true)
BAD_TX=$(echo $R | jq -r .transactionHash)
echo "revert: status $(echo $R | jq -r .status) tx $BAD_TX"
[ "$(echo $R | jq -r .status)" = 0x0 ]

jq -n --arg safe $SAFE --arg oa $OA --arg ob $OB --arg g1 $GUARDIAN_1 --arg g2 $GUARDIAN_2 --arg pa $PUB_A --arg pb $PUB_B \
  --arg ix $ISSUER_X --arg iy $ISSUER_Y --arg create "$CREATE_TX" --arg fund $FUND_TX --arg ok $OK_TX --arg okgas $OK_GAS \
  --arg bad $BAD_TX --arg dep $DEP --arg bob $BOB \
  '{safe:$safe,ownerA:$oa,ownerB:$ob,guardian1:$g1,guardian2:$g2,pubA:$pa,pubB:$pb,issuerX:$ix,issuerY:$iy,
    deployer:$dep,recipient:$bob,createTxs:($create|split(",")),fundTx:$fund,spendTx:$ok,spendGas:($okgas|tonumber),revertTx:$bad}' >$LOG
echo "wrote $LOG"
