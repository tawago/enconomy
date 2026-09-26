#!/usr/bin/env bash
# Relayer dry run on an anvil fork of Ethereum Sepolia, attestation bodies from the real server code. Test keys only.
#   anvil --fork-url https://sepolia.gateway.tenderly.co --hardfork osaka --port 8612 --silent &
#   RPC=http://127.0.0.1:8612 test/dryrun.sh
# Checks: success spend, idempotent rerun, NOT_NEAR skip, tampered POP2 -> BadAttestation, stale nonce, unknown Safe device.
set -euo pipefail
cd "$(dirname "$0")/.."
RELAYER=$PWD; C=$RELAYER/../contracts
RPC=${RPC:-http://127.0.0.1:8612}
[ "$(cast chain-id --rpc-url "$RPC")" = 11155111 ] || { echo "need an anvil fork of sepolia at $RPC" >&2; exit 1; }
K0=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80       # anvil 0: deployer
export RELAYER_PK=0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6   # anvil 3
TO=0x000000000000000000000000000000000000beef WEI=500000000000000
OUT=$(mktemp -d); export OUT_DIR=$OUT RPC
FIX="uv run --quiet --project ../server python test/make_fixture.py"
PY="uv run --quiet --with cryptography python3 $C/script/pop_sigs.py"

cd "$C"
export DEPLOY_OUT=deployments/anvil-11155111.json PRIVATE_KEY=$K0
forge script script/Deploy.s.sol --rpc-url "$RPC" --broadcast --silent
export GUARD=$(jq -r .PopSafeGuard $DEPLOY_OUT) SETUP=$(jq -r .PopSafeSetup $DEPLOY_OUT) OWNER_FACTORY=$(jq -r .P256OwnerFactory $DEPLOY_OUT)
IPUB=$($PY pub 0xC0FFEE)
export PUB_A=$($PY pub 0xA1) PUB_B=$($PY pub 0xB1) ISSUER_X=0x${IPUB:4:64} ISSUER_Y=0x${IPUB:68:64} \
  GUARDIAN_1=0x70997970C51812dc3A010C7d01b50e0d17dc79C8 GUARDIAN_2=0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC \
  DELAY=300 GRACE=600 SALT=$(date +%s)
SAFE=$(forge script script/CreatePopSafe.s.sol --rpc-url "$RPC" --broadcast | awk '/ safe 0x/{print $2}' | tr 'A-F' 'a-f')
cast send $SAFE --value 0.01ether --rpc-url $RPC --private-key $K0 >/dev/null
echo "safe $SAFE guard $GUARD"
cd "$RELAYER"
nonce() { cast call $SAFE 'nonce()(uint256)' --rpc-url $RPC; }
field() { node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const o=JSON.parse(s);console.log(o[process.argv[1]]??"")})' "$1"; }

# 1. spend
N=$(nonce); $FIX $SAFE $TO $WEI $N > $OUT/ok.json
R1=$(PRINT_SIGS=1 node relay.mjs --fixture $OUT/ok.json 2>$OUT/sigs.txt) || { echo "$R1"; cat $OUT/sigs.txt; exit 1; }
echo "spend: $R1"
[ "$(echo "$R1" | field status)" = success ]
[ "$(cast balance $TO --rpc-url $RPC)" -ge $WEI ]
grep -q '000000ac504f5056$' $OUT/sigs.txt

# 2. rerun: same tx hash, nothing sent
R2=$(node relay.mjs --fixture $OUT/ok.json)
echo "rerun: $R2"
[ "$(echo "$R2" | field tx_hash)" = "$(echo "$R1" | field tx_hash)" ] && [ "$(echo "$R2" | field resent)" = false ]

# 3. NOT_NEAR: server withholds POP2 + owner sigs, relayer skips
N=$(nonce); $FIX $SAFE $TO $WEI $N NOT_NEAR > $OUT/far.json
R3=$(node relay.mjs --fixture $OUT/far.json || true); echo "not near: $R3"
[ "$(echo "$R3" | field error)" = not_near ]

# 4. tampered POP2 signature -> the guard's verifier refuses (simulate), nothing sent
$FIX $SAFE $TO $WEI $N > $OUT/bad.json
node -e 'const f=require("fs");const o=JSON.parse(f.readFileSync(process.argv[1]));const t=o.att.tail_hex;
  const i=2+2*110;o.att.tail_hex=t.slice(0,i)+(t[i]==="0"?"1":"0")+t.slice(i+1);f.writeFileSync(process.argv[1],JSON.stringify(o))' $OUT/bad.json
R4=$(node relay.mjs --fixture $OUT/bad.json || true); echo "tampered: $R4"
[ "$(echo "$R4" | field error)" = BadAttestation ]

# 5. stale nonce: an attestation for an already used nonce
$FIX $SAFE $TO $WEI $((N - 1)) > $OUT/stale.json
R5=$(node relay.mjs --fixture $OUT/stale.json || true); echo "stale: $R5"
[ "$(echo "$R5" | field error)" = stale_nonce ]

# 6. a Safe without this device pair: attestation names devices the guard doesn't know
node -e 'const f=require("fs");const o=JSON.parse(f.readFileSync(process.argv[1]));o.session_id="ffff";o.att.dev_a="0x"+"77".repeat(32);f.writeFileSync(process.argv[1],JSON.stringify(o))' $OUT/bad.json
R6=$(node relay.mjs --fixture $OUT/bad.json || true); echo "unknown device: $R6"
[ "$(echo "$R6" | field error)" = unknown_device ]
[ "$(nonce)" = "$N" ]
echo "DRYRUN OK"
