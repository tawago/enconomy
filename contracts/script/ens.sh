#!/usr/bin/env bash
# enconomy ENSv2 bootstrap + ops (Sepolia). Idempotent: every step reads chain state first.
#
#   script/ens.sh bootstrap
#   script/ens.sh claim <label>
#   script/ens.sh touch <label>
#   script/ens.sh record <labelA> <labelB> [sessionIdHex32]
#   script/ens.sh zk <meetingId>
#   script/ens.sh void <meetingId>
#   script/ens.sh status <name>            e.g. alice.enconomy.eth or enconomy.eth
#   script/ens.sh addr                      print the key's address and balance
#
# env: ENS_KEY_FILE (default ~/.enconomy/ens-sepolia.key), ETH_RPC (default publicnode Sepolia),
#      ENS_PARENT (default enconomy.eth), ENS_EVENT_NAME, ENS_SITE_URL, ENS_OUT (deployments json).
# Never prints the private key. Do not run with `bash -x`.
set -euo pipefail
set +x

HERE="$(cd "$(dirname "$0")/.." && pwd)"
ENS_KEY_FILE="${ENS_KEY_FILE:-$HOME/.enconomy/ens-sepolia.key}"
RPC="${ETH_RPC:-https://ethereum-sepolia-rpc.publicnode.com}"
PARENT="${ENS_PARENT:-enconomy.eth}"
EVENT_NAME="${ENS_EVENT_NAME:-ETHGlobal Tokyo 2026}"
SITE_URL="${ENS_SITE_URL:-https://enconomy.pages.dev/}"
OUT="${ENS_OUT:-$HERE/deployments/sepolia.json}"
CHAIN_ID=11155111

# ---- ENS v2 Sepolia (contracts-v2 71a3b733, sepolia-deployment-2026-09-15)
UR=0xeEeEEEeE14D718C2B47D9923Deab1335E144EeEe
ROOT_REGISTRY=0x9703dbd26dab89504490994138cf2c575251a9ce
ETH_REGISTRAR=0xabe76f6c8dfced81aa5a2bb8034202a7136b94ca
VERIFIABLE_FACTORY=0x9e726eb570beb6bceb495ab8cda7df517d4e841c
USER_REGISTRY_IMPL=0xa80338aaa8d23831cea25e858d1774534abb0263
MOCK_USDC=0x16f95d91dba7da3aca778ec053df0ff6c6a8aa8e
CREATE2_DEPLOYER=0x4e59b44847b379578588920cA78FbF26c0B4956C

ALL_ROLES=0x1111111111111111111111111111111111111111111111111111111111111111
PARENT_DURATION=31536000          # 365 d
NAME_TTL=$((90 * 86400))          # attendee names: 90 d
ZERO32=0x0000000000000000000000000000000000000000000000000000000000000000
ZERO_ADDR=0x0000000000000000000000000000000000000000

TXS=0

die() { echo "error: $*" >&2; exit 1; }
log() { echo "· $*" >&2; }
lc() { tr '[:upper:]' '[:lower:]'; }

load_key() {
  [[ -r "$ENS_KEY_FILE" ]] || die "key file $ENS_KEY_FILE not readable"
  PK="$(tr -d '[:space:]' < "$ENS_KEY_FILE")"
  [[ "$PK" == 0x* ]] || PK="0x$PK"
  ME="$(cast wallet address --private-key "$PK")"
  ME_LC="$(echo "$ME" | lc)"
}

c() { cast call --rpc-url "$RPC" "$@"; }                 # typed call
first() { awk '{print $1}'; }                             # strip cast's " [1e6]" suffix

send() {  # send <to> <sig|calldata> [args...]
  local out st
  out="$(cast send --rpc-url "$RPC" --private-key "$PK" --json "$@")" || die "tx failed: $1 $2"
  st="$(echo "$out" | jq -r .status)"
  [[ "$st" == "0x1" || "$st" == "1" ]] || die "tx reverted: $1 $2 $(echo "$out" | jq -r .transactionHash)"
  TXS=$((TXS + 1))
  log "tx $(echo "$out" | jq -r .transactionHash) (${2:0:60})"
  LAST_RECEIPT="$out"
}

is_anvil() { cast client --rpc-url "$RPC" 2>/dev/null | grep -qi anvil; }
block_ts() { cast block latest -f timestamp --rpc-url "$RPC"; }

# raw word i (0-based) of an ABI-encoded return as 0x-hex
word() { echo "0x${1:$((2 + 64 * $2)):64}"; }
w2addr() { echo "0x${1:26:40}" | lc; }

dns_encode() {  # a.b.eth -> 0x01610162036574 68 00
  local out="0x" l IFS=.
  for l in $1; do out+="$(printf '%02x' ${#l})$(cast from-utf8 "$l" | cut -c3-)"; done
  echo "${out}00"
}

check_label() {
  [[ "$1" =~ ^[a-z0-9-]{3,32}$ ]] || die "label '$1' must be [a-z0-9-], 3-32 chars"
}

parent_label() {
  [[ "$PARENT" =~ ^([a-z0-9-]+)\.eth$ ]] || die "ENS_PARENT must be <label>.eth"
  echo "${BASH_REMATCH[1]}"
}

load_state() {
  [[ -r "$OUT" ]] || die "no $OUT; run bootstrap first"
  REGISTRY="$(jq -r .registry "$OUT")"
  RESOLVER="$(jq -r .meetResolver "$OUT")"
  [[ "$(jq -r .parent "$OUT")" == "$PARENT" ]] || die "$OUT is for $(jq -r .parent "$OUT"), not $PARENT"
}

reg_state() {  # reg_state <registry> <labelhash>  -> sets S_STATUS S_EXPIRY S_OWNER S_TOKEN S_RES
  local raw
  raw="$(c "$1" "$(cast calldata 'getState(uint256)' "$2")")"
  S_STATUS=$(( $(word "$raw" 0) ))
  S_EXPIRY=$(( $(word "$raw" 1) ))
  S_OWNER="$(w2addr "$(word "$raw" 2)")"
  S_TOKEN="$(word "$raw" 3)"
  S_RES="$(word "$raw" 4)"
}

# ------------------------------------------------------------------ bootstrap

cmd_bootstrap() {
  load_key
  local label lh pnode pdns chain
  label="$(parent_label)"
  lh="$(cast keccak "$label")"
  pnode="$(cast namehash "$PARENT")"
  pdns="$(dns_encode "$PARENT")"
  chain="$(cast chain-id --rpc-url "$RPC")"
  [[ "$chain" == "$CHAIN_ID" ]] || die "chain id $chain != $CHAIN_ID"
  log "key $ME  rpc $RPC  parent $PARENT"
  [[ "$(cast code "$ME" --rpc-url "$RPC")" == "0x" ]] || die "$ME has code (EIP-7702 delegation?)"

  # 1. discovery / self-check
  local root eth_reg eth_reg2
  root="$(c $UR 'ROOT_REGISTRY()(address)' | lc)"
  [[ "$root" == "$(echo $ROOT_REGISTRY | lc)" ]] || die "UR.ROOT_REGISTRY $root != $ROOT_REGISTRY (ENS redeployed?)"
  eth_reg="$(c $ROOT_REGISTRY 'getSubregistry(string)(address)' eth | lc)"
  eth_reg2="$(c $ETH_REGISTRAR 'ETH_REGISTRY()(address)' | lc)"
  [[ "$eth_reg" == "$eth_reg2" ]] || die "eth registry mismatch $eth_reg vs $eth_reg2"
  ETH_REGISTRY="$eth_reg"
  reg_state "$ETH_REGISTRY" "$lh"
  if [[ $S_STATUS -eq 2 && "$S_OWNER" != "$ME_LC" ]]; then
    die "$PARENT is registered to $S_OWNER, not us"
  fi

  # 2. UserRegistry proxy via VerifiableFactory (deterministic address)
  local salt outer logic initcode registry
  salt="$(cast to-dec "$(cast keccak "enconomy:$PARENT:registry:v1")")"
  outer="$(cast keccak "$(cast abi-encode 'f(address,uint256)' "$ME" "$salt")")"
  logic="$(c $VERIFIABLE_FACTORY 'proxyLogic()(address)')"
  initcode="0x3d604d80600a3d3981f3363d3d373d3d3d363d73${logic:2}5af43d82803e903d91602b57fd5bf3${outer:2}"
  registry="$(cast create2 --deployer $VERIFIABLE_FACTORY --salt "$outer" --init-code "$initcode" | lc)"
  if [[ "$(cast code "$registry" --rpc-url "$RPC")" == "0x" ]]; then
    log "deploying UserRegistry proxy -> $registry"
    send $VERIFIABLE_FACTORY 'deployProxy(address,uint256,bytes)' $USER_REGISTRY_IMPL "$salt" \
      "$(cast calldata 'initialize((address,uint256)[])' "[($ME,$ALL_ROLES)]")"
    [[ "$(cast code "$registry" --rpc-url "$RPC")" != "0x" ]] || die "proxy not at predicted $registry"
  else
    log "UserRegistry exists $registry"
  fi
  REGISTRY="$registry"

  # 3. MeetResolver via CREATE2 deployer. Site/event are set after deploy so the address
  #    only changes when the bytecode, registry or parent changes.
  (cd "$HERE" && forge build --silent)
  local bytecode ctor rsalt rinit resolver
  bytecode="$(jq -r .bytecode.object "$HERE/out/MeetResolver.sol/MeetResolver.json")"
  ctor="$(cast abi-encode 'f(address,bytes32,bytes,address,address,string,string)' \
    "$REGISTRY" "$pnode" "$pdns" "$ME" "$ME" "" "")"
  rsalt="$(cast keccak "enconomy:$PARENT:meetresolver:v1")"
  rinit="${bytecode}${ctor:2}"
  resolver="$(cast create2 --deployer $CREATE2_DEPLOYER --salt "$rsalt" --init-code "$rinit" | lc)"
  [[ "$(cast code $CREATE2_DEPLOYER --rpc-url "$RPC")" != "0x" ]] || die "no CREATE2 deployer"
  if [[ "$(cast code "$resolver" --rpc-url "$RPC")" == "0x" ]]; then
    log "deploying MeetResolver -> $resolver"
    send $CREATE2_DEPLOYER "${rsalt}${rinit:2}"
    [[ "$(cast code "$resolver" --rpc-url "$RPC")" != "0x" ]] || die "resolver not at predicted $resolver"
  else
    log "MeetResolver exists $resolver"
  fi
  RESOLVER="$resolver"
  local cur_ev cur_site
  cur_ev="$(c "$RESOLVER" 'eventName()(string)')"
  cur_site="$(c "$RESOLVER" 'siteUrl()(string)')"
  if [[ "$cur_ev" != "\"$EVENT_NAME\"" || "$cur_site" != "\"$SITE_URL\"" ]]; then
    send "$RESOLVER" 'setSite(string,string)' "$EVENT_NAME" "$SITE_URL"
  fi

  # 4. the 2LD (commit / wait 60 s / register), paid in MockUSDC
  reg_state "$ETH_REGISTRY" "$lh"
  if [[ $S_STATUS -ne 2 ]]; then
    [[ "$(c $ETH_REGISTRAR 'isAvailable(string)(bool)' "$label")" == "true" ]] || die "$label not available"
    local price base prem total bal allow secret commitment cat minage now
    price="$(c $ETH_REGISTRAR 'getRegisterPrice(string,uint64,address)(uint256,uint256)' "$label" $PARENT_DURATION $MOCK_USDC)"
    base="$(echo "$price" | sed -n 1p | first)"; prem="$(echo "$price" | sed -n 2p | first)"
    total=$((base + prem))
    log "price $base + $prem MockUSDC units"
    bal="$(c $MOCK_USDC 'balanceOf(address)(uint256)' "$ME" | first)"
    (( bal >= total )) || send $MOCK_USDC 'mint(address,uint256)' "$ME" $((total - bal + 1000000))
    allow="$(c $MOCK_USDC 'allowance(address,address)(uint256)' "$ME" $ETH_REGISTRAR | first)"
    (( allow >= total )) || send $MOCK_USDC 'approve(address,uint256)' $ETH_REGISTRAR $((total + 1000000))
    secret="$(cast keccak "enconomy-bootstrap:$label:$ME")"
    commitment="$(c $ETH_REGISTRAR 'makeCommitment(string,address,bytes32,address,address,uint64,bytes32)(bytes32)' \
      "$label" "$ME" "$secret" "$REGISTRY" "$RESOLVER" $PARENT_DURATION $ZERO32)"
    cat="$(c $ETH_REGISTRAR 'commitmentAt(bytes32)(uint64)' "$commitment" | first)"
    now="$(block_ts)"
    if (( cat == 0 || now - cat > 86000 )); then
      send $ETH_REGISTRAR 'commit(bytes32)' "$commitment"
      cat="$(c $ETH_REGISTRAR 'commitmentAt(bytes32)(uint64)' "$commitment" | first)"
    else
      log "reusing commitment from ts $cat"
    fi
    minage="$(c $ETH_REGISTRAR 'MIN_COMMITMENT_AGE()(uint64)' | first)"
    if is_anvil; then
      now="$(block_ts)"
      if (( now <= cat + minage )); then
        cast rpc evm_increaseTime $((cat + minage + 1 - now)) --rpc-url "$RPC" >/dev/null
        cast rpc evm_mine --rpc-url "$RPC" >/dev/null
      fi
    else
      log "waiting for commitment age ${minage}s"
      while (( $(block_ts) <= cat + minage )); do sleep 5; done
    fi
    send $ETH_REGISTRAR 'register(string,address,bytes32,address,address,uint64,address,bytes32)' \
      "$label" "$ME" "$secret" "$REGISTRY" "$RESOLVER" $PARENT_DURATION $MOCK_USDC $ZERO32
    reg_state "$ETH_REGISTRY" "$lh"
    [[ $S_STATUS -eq 2 && "$S_OWNER" == "$ME_LC" ]] || die "2LD register did not stick"
  else
    log "$PARENT registered to us (expiry $S_EXPIRY)"
  fi

  # 5. subregistry / resolver pointers on the 2LD (repair if a rerun deployed a new resolver)
  [[ "$(c "$ETH_REGISTRY" 'getSubregistry(string)(address)' "$label" | lc)" == "$REGISTRY" ]] \
    || send "$ETH_REGISTRY" 'setSubregistry(uint256,address)' "$S_TOKEN" "$REGISTRY"
  [[ "$(c "$ETH_REGISTRY" 'getResolver(string)(address)' "$label" | lc)" == "$RESOLVER" ]] \
    || send "$ETH_REGISTRY" 'setResolver(uint256,address)' "$S_TOKEN" "$RESOLVER"

  # 6. UserRegistry parent + roles (single-key: admin == hot == attester holds ALL_ROLES)
  local par praw
  praw="$(c "$REGISTRY" "$(cast calldata 'getParent()')")"
  par="$(w2addr "$(word "$praw" 0)")"
  if [[ "$par" != "$ETH_REGISTRY" ]]; then
    send "$REGISTRY" 'setParent(address,string)' "$ETH_REGISTRY" "$label"
  fi
  local roles
  roles="$(c "$REGISTRY" 'roles(uint256,address)(uint256)' 0 "$ME" | first)"
  [[ "$(cast to-hex "$roles" | lc)" == "$ALL_ROLES" ]] || die "roles(0,$ME) = $(cast to-hex "$roles"), want ALL_ROLES"
  [[ "$(c "$RESOLVER" 'attester()(address)' | lc)" == "$ME_LC" ]] || die "resolver attester != $ME"
  [[ "$(c "$RESOLVER" 'REG()(address)' | lc)" == "$REGISTRY" ]] || die "resolver REG != registry"

  # 7. end-to-end read through the Universal Resolver
  local desc
  desc="$(ur_text "$PARENT" description)"
  [[ -n "$desc" ]] || die "UR text($PARENT, description) empty"
  log "UR $PARENT description: $desc"

  # 8. state file
  local dblock
  dblock="$(c "$RESOLVER" 'DEPLOY_BLOCK()(uint256)' | first)"
  mkdir -p "$(dirname "$OUT")"
  jq -n --arg parent "$PARENT" --arg registry "$(cast to-check-sum-address "$REGISTRY")" \
    --arg meetResolver "$(cast to-check-sum-address "$RESOLVER")" --arg me "$ME" \
    --arg rootRegistry "$(cast to-check-sum-address $ROOT_REGISTRY)" \
    --arg ethRegistry "$(cast to-check-sum-address "$ETH_REGISTRY")" --arg ur "$UR" \
    --argjson deployBlock "$dblock" --argjson chainId $CHAIN_ID \
    '{parent:$parent, registry:$registry, meetResolver:$meetResolver, admin:$me, hot:$me, attester:$me,
      rootRegistry:$rootRegistry, ethRegistry:$ethRegistry, universalResolver:$ur,
      deployBlock:$deployBlock, chainId:$chainId}' > "$OUT.tmp"
  if [[ -r "$OUT" ]] && cmp -s "$OUT" "$OUT.tmp"; then rm "$OUT.tmp"; else mv "$OUT.tmp" "$OUT"; log "wrote $OUT"; fi
  echo "bootstrap ok; txs sent: $TXS"
}

# ------------------------------------------------------------------ ops

cmd_claim() {
  local label="${1:?label}"; check_label "$label"
  load_key; load_state
  local lh exp
  lh="$(cast keccak "$label")"
  reg_state "$REGISTRY" "$lh"
  if [[ $S_STATUS -eq 2 ]]; then
    [[ "$S_OWNER" == "$ME_LC" ]] || die "$label.$PARENT owned by $S_OWNER"
    log "$label.$PARENT already registered (expiry $S_EXPIRY)"
  else
    exp=$(( $(block_ts) + NAME_TTL ))
    send "$REGISTRY" 'register(string,address,address,address,uint256,uint64)' \
      "$label" "$ME" $ZERO_ADDR "$RESOLVER" 0 $exp
    send "$RESOLVER" 'touch(string)' "$label"
  fi
  echo "$label.$PARENT  node $(cast namehash "$label.$PARENT")  txs $TXS"
}

cmd_touch() {
  local label="${1:?label}"; check_label "$label"
  load_key; load_state
  send "$RESOLVER" 'touch(string)' "$label"
}

cmd_record() {
  local a="${1:?labelA}" b="${2:?labelB}" sid="${3:-}"
  check_label "$a"; check_label "$b"
  load_key; load_state
  [[ -n "$sid" ]] || sid="$(openssl rand -hex 16)"
  sid="${sid#0x}"
  [[ "$sid" =~ ^[0-9a-fA-F]{32}$ ]] || die "session id must be 32 hex chars"
  local mid tb ev lha lhb first_time
  mid="$(cast keccak "$(cast from-utf8 'enconomy/meet/v1')${sid}")"
  tb=$(( $(date +%s) / 3600 ))
  ev="$(cast keccak "0x$(openssl rand -hex 64)")"   # rehearsal evidence: no real transcripts
  lha="$(cast keccak "$a")"; lhb="$(cast keccak "$b")"
  first_time="$(cast call --rpc-url "$RPC" --from "$ME" "$RESOLVER" \
    'record(bytes32,bytes32,bytes32,uint32,bytes32)(bool)' "$mid" "$lha" "$lhb" $tb "$ev")"
  send "$RESOLVER" 'record(bytes32,bytes32,bytes32,uint32,bytes32)' "$mid" "$lha" "$lhb" $tb "$ev"
  echo "meetingId $mid  session $sid  firstTime $first_time  tx $(echo "$LAST_RECEIPT" | jq -r .transactionHash)"
}

cmd_zk() {
  local mid="${1:?meetingId}"; load_key; load_state
  send "$RESOLVER" 'markZkVerified(bytes32)' "$mid"
}

cmd_void() {
  local mid="${1:?meetingId}"; load_key; load_state
  send "$RESOLVER" 'voidMeeting(bytes32)' "$mid"
}

ur_text() {  # ur_text <name> <key>  -> decoded string (dies on UR revert)
  local name="$1" key="$2" raw
  raw="$(cast call --rpc-url "$RPC" $UR 'resolve(bytes,bytes)(bytes,address)' "$(dns_encode "$name")" \
    "$(cast calldata 'text(bytes32,string)' "$(cast namehash "$name")" "$key")" | sed -n 1p)"
  cast abi-decode 'f()(string)' "$raw" | sed -e 's/^"//' -e 's/"$//'
}

cmd_status() {
  local name="${1:?name}" k v raw
  for k in eth.enconomy.met eth.enconomy.meetings eth.enconomy.zk description url; do
    if v="$(ur_text "$name" "$k" 2>&1)"; then printf '%-22s %s\n' "$k" "\"$v\""
    else printf '%-22s ERROR %s\n' "$k" "$(echo "$v" | tail -1)"; fi
  done
  if raw="$(cast call --rpc-url "$RPC" $UR 'resolve(bytes,bytes)(bytes,address)' "$(dns_encode "$name")" \
      "$(cast calldata 'addr(bytes32)' "$(cast namehash "$name")")" 2>&1)"; then
    printf '%-22s %s\n' "addr" "$(cast abi-decode 'f()(address)' "$(echo "$raw" | sed -n 1p)")"
    printf '%-22s %s\n' "resolver" "$(echo "$raw" | sed -n 2p)"
  else
    printf '%-22s ERROR %s\n' "addr" "$(echo "$raw" | tail -1)"
  fi
}

cmd_addr() {
  load_key
  echo "$ME  balance $(cast balance "$ME" --ether --rpc-url "$RPC") ETH"
}

case "${1:-}" in
  bootstrap) shift; cmd_bootstrap "$@" ;;
  claim) shift; cmd_claim "$@" ;;
  touch) shift; cmd_touch "$@" ;;
  record) shift; cmd_record "$@" ;;
  zk) shift; cmd_zk "$@" ;;
  void) shift; cmd_void "$@" ;;
  status) shift; cmd_status "$@" ;;
  addr) shift; cmd_addr "$@" ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
