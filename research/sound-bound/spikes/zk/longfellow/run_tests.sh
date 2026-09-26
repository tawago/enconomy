#!/bin/bash
# Accept/reject matrix for sbzk on the real fixtures. Run under tools/heavy.sh:
#   ../tools/heavy.sh lf-sbzk-tests ./run_tests.sh
# Needs build/sbzk and out/sbzk1.circuit (see README).
cd "$(dirname "$0")"
PY=${PY:-../../../../proximity-echo/.venv/bin/python3}
C=out/sbzk1.circuit; T=out/t; mkdir -p $T
pass=0; fail=0
expect() {  # expect <want: ok|refuse|accept|reject> <label> <cmd...>
  want=$1; label=$2; shift 2
  out=$("$@" 2>&1); rc=$?
  case $want in ok|accept) good=$([ $rc -eq 0 ] && echo 1);; refuse|reject) good=$([ $rc -eq 1 ] && echo 1);; esac
  line=$(echo "$out" | grep -E "^(prove|verify)" | tail -1)
  if [ "$good" = 1 ]; then pass=$((pass+1)); echo "PASS $label [$want] $line"; else fail=$((fail+1)); echo "FAIL $label [$want rc=$rc] $out"; fi
}
settamper() { sed -i '' "s/^$2 .*/$2 $3/" $1; }

# 1. every fixture, honest witness, prover A: NEAR -> proof verifies; NOT_NEAR -> prover refuses,
#    forced proof rejected by verifier.
for f in ../fixtures/*.json; do
  s=$(basename $f .json); d=$T/$s
  info=$($PY prep.py $f $d); echo "$info"
  if echo "$info" | grep -q "verdict=NEAR"; then
    expect ok     "$s prove"  ./build/sbzk prove $C $d/witness.txt $d/proof.bin
    expect accept "$s verify" ./build/sbzk verify $C $d/public.txt $d/proof.bin
  else
    expect refuse "$s prove(NOT_NEAR)"        ./build/sbzk prove $C $d/witness.txt $d/proof.bin
    expect ok     "$s prove --force"          ./build/sbzk prove $C $d/witness.txt $d/forged.bin --force
    expect reject "$s verify forged(NOT_NEAR)" ./build/sbzk verify $C $d/public.txt $d/forged.bin
  fi
done

# 2. prover B on a NEAR fixture (different holder secret -> different nullifier)
N=180ca04b; d=$T/${N}_B; $PY prep.py ../fixtures/$N.json $d --prover B
expect ok     "$N proverB prove"  ./build/sbzk prove $C $d/witness.txt $d/proof.bin
expect accept "$N proverB verify" ./build/sbzk verify $C $d/public.txt $d/proof.bin

# 3. forge path sanity: forced proof on an HONEST witness must still verify
d=$T/$N; expect ok "$N honest --force" ./build/sbzk prove $C $d/witness.txt $d/honest_forced.bin --force
expect accept "$N verify honest forced" ./build/sbzk verify $C $d/public.txt $d/honest_forced.bin

# 4. private-side tampering on NEAR fixtures
for N in 180ca04b 2dc2eb59; do
for k in half role nonce_w sig credsig expired; do
  d=$T/${N}_$k; $PY prep.py ../fixtures/$N.json $d --tamper $k >/dev/null
  expect refuse "$N tamper=$k prove"          ./build/sbzk prove $C $d/witness.txt $d/proof.bin
  expect ok     "$N tamper=$k prove --force"  ./build/sbzk prove $C $d/witness.txt $d/forged.bin --force
  expect reject "$N tamper=$k verify forged"  ./build/sbzk verify $C $d/public.txt $d/forged.bin
done; done

# 4b. high-S variant of a valid signature: circuit accepts (no low-S rule), documented
N=180ca04b; d=$T/${N}_highs; $PY prep.py ../fixtures/$N.json $d --tamper highs >/dev/null
expect ok     "$N highS prove (malleable sig accepted)" ./build/sbzk prove $C $d/witness.txt $d/proof.bin
expect accept "$N highS verify" ./build/sbzk verify $C $d/public.txt $d/proof.bin

# 5. public-side tampering: honest proof, verifier given different public inputs
N=180ca04b; d=$T/$N
for k in nonce attempt issuer_x now nullifier; do
  cp $d/public.txt $d/pub_$k.txt
  case $k in
    nonce)     settamper $d/pub_$k.txt nonce $(printf '%064x' 1);;
    attempt)   settamper $d/pub_$k.txt attempt 01;;
    issuer_x)  settamper $d/pub_$k.txt issuer_x $(grep '^A.dpk' $d/witness.txt | cut -c7-70);;
    now)       settamper $d/pub_$k.txt now 000000006ab85c81;;
    nullifier) settamper $d/pub_$k.txt nullifier $(printf '%064x' 2);;
  esac
  expect reject "$N public $k changed" ./build/sbzk verify $C $d/pub_$k.txt $d/proof.bin
done
# proof from session X presented for session Y's public inputs
expect reject "proof(180ca04b) vs public(2dc2eb59)" ./build/sbzk verify $C $T/2dc2eb59/public.txt $T/180ca04b/proof.bin
# truncated proof
head -c 200000 $T/180ca04b/proof.bin > $T/trunc.bin
expect reject "truncated proof" ./build/sbzk verify $C $T/180ca04b/public.txt $T/trunc.bin

echo "RESULT pass=$pass fail=$fail"
[ $fail -eq 0 ]
