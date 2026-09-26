#!/bin/bash
# Reviewer attack matrix (adds to run_tests.sh). Run under tools/heavy.sh:
#   ../tools/heavy.sh review-lf-attacks ./review/attacks.sh
cd "$(dirname "$0")/.."
PY=${PY:-../../../../proximity-echo/.venv/bin/python3}
C=out/sbzk1.circuit; T=out/review/atk; mkdir -p $T
pass=0; fail=0
expect() {
  want=$1; label=$2; shift 2
  out=$("$@" 2>&1); rc=$?
  case $want in ok|accept) good=$([ $rc -eq 0 ] && echo 1);; refuse|reject) good=$([ $rc -eq 1 ] && echo 1);; esac
  line=$(echo "$out" | grep -E "^(prove|verify|witness)" | tr '\n' ' ')
  if [ "$good" = 1 ]; then pass=$((pass+1)); echo "PASS $label [$want] $line"; else fail=$((fail+1)); echo "FAIL $label [$want rc=$rc] $out"; fi
}
bad3() {  # honest prover must refuse, forged proof must be rejected
  d=$1; l=$2
  expect refuse "$l prove"          ./build/sbzk prove $C $d/witness.txt $d/proof.bin
  expect ok     "$l prove --force"  ./build/sbzk prove $C $d/witness.txt $d/forged.bin --force
  expect reject "$l verify forged"  ./build/sbzk verify $C $d/public.txt $d/forged.bin
}
good2() {
  d=$1; l=$2
  expect ok     "$l prove"  ./build/sbzk prove $C $d/witness.txt $d/proof.bin
  expect accept "$l verify" ./build/sbzk verify $C $d/public.txt $d/proof.bin
}

echo "== A1 role swap on 2dc2eb59 (7.86 cm; swapped = -7.86 cm, inside the window, so only role binding stops it)"
d=$T/swap; $PY prep.py ../fixtures/2dc2eb59.json $d --tamper role; bad3 $d "A1 role swap"

echo "== A2 cross-session splice: A from 9afb91c6 (211 cm), B from d283370f (225 cm) -> would read 17.5 cm"
d=$T/splice; $PY prep.py ../fixtures/9afb91c6.json $d >/dev/null; $PY prep.py ../fixtures/d283370f.json $T/splice_y >/dev/null
grep -v '^B\.' $d/witness.txt > $d/w2; grep '^B\.' $T/splice_y/witness.txt >> $d/w2; mv $d/w2 $d/witness.txt
bad3 $d "A2 splice (nonce of X)"
d2=$T/splice_ynonce; mkdir -p $d2; cp $d/witness.txt $d2/; cp $T/splice_y/public.txt $d2/
sed -i '' "s/^nonce .*/$(grep '^nonce' $d2/public.txt)/; s/^nullifier .*/$(grep '^nullifier' $d2/public.txt)/" $d2/witness.txt
bad3 $d2 "A2 splice (nonce of Y)"

echo "== A3 expiry byte order: exp=0x6ade34e1"
d=$T/exp_after;  $PY prep.py ../fixtures/180ca04b.json $d --now 1792947456; bad3 $d "A3 now=0x6ade3500 (> exp, LE-order bug would accept)"
d=$T/exp_before; $PY prep.py ../fixtures/180ca04b.json $d --now 1792947199; good2 $d "A3 now=0x6ade33ff (< exp, LE-order bug would refuse)"
d=$T/exp_equal;  $PY prep.py ../fixtures/180ca04b.json $d --now 1792947425; good2 $d "A3 now=exp (<= is inclusive)"

echo "== A4 nullifier re-roll (known gap): same session 180ca04b, fresh holder secret"
d=$T/reroll; $PY prep.py ../fixtures/180ca04b.json $d >/dev/null
H=$($PY -c "import secrets;print(secrets.token_hex(32))"); NO=$(grep '^nonce' $d/public.txt | cut -d' ' -f2)
NU=$($PY -c "import hashlib;print(hashlib.sha256(bytes.fromhex('$H')+bytes.fromhex('$NO')).hexdigest())")
sed -i '' "s/^holder .*/holder $H/; s/^nullifier .*/nullifier $NU/" $d/witness.txt
sed -i '' "s/^nullifier .*/nullifier $NU/" $d/public.txt
good2 $d "A4 reroll (ACCEPTED = double-count possible)"
echo "   nullifiers: honest=$(grep '^nullifier' out/review/b9e4dd4b/public.txt 2>/dev/null | cut -c11-26)… reroll=${NU:0:16}…"

echo "== A5 proof bytes: trailing junk / one flipped byte"
d=out/review/b9e4dd4b
cp $d/proof.bin $T/junk.bin; printf 'JUNKJUNK' >> $T/junk.bin
expect accept "A5 proof + 8 junk bytes (parser ignores trailer; malleable encoding, not a soundness bug)" ./build/sbzk verify $C $d/public.txt $T/junk.bin
cp $d/proof.bin $T/flip.bin; printf '\x55' | dd of=$T/flip.bin bs=1 seek=300000 conv=notrunc 2>/dev/null
expect reject "A5 one byte flipped at offset 300000" ./build/sbzk verify $C $d/public.txt $T/flip.bin

echo "== S synthetic (software throwaway keys + own issuer): threshold edges, i32 extremes, same key both roles"
S=$T/synth; mkdir -p $S
syn() { name=$1; shift; $PY review/synth.py $S/$name.json "$@"; $PY prep.py $S/$name.json $S/$name >/dev/null; }
syn b167 1167 1000;  good2 $S/b167 "S1 d=167 (59.67 cm)"
syn b168 1168 1000;  bad3  $S/b168 "S2 d=168 (60.03 cm)"
syn bm55 1000 1055;  good2 $S/bm55 "S3 d=-55 (-19.65 cm)"
syn bm56 1000 1056;  bad3  $S/bm56 "S4 d=-56 (-20.01 cm)"
syn ext1 2147483647 -2147483648; bad3 $S/ext1 "S5 d=2^32-1"
syn ext2 -2147483648 2147483647; bad3 $S/ext2 "S6 d=-(2^32-1)"
syn same 1010 1000 --same-key; good2 $S/same "S8 same device key in both roles (ACCEPTED; no dpk_A != dpk_B check)"
echo "   S1/S3/S8 verify under a self-made issuer key: the verifier tool trusts issuer_x/y from public.txt (must be pinned by policy)"

echo "RESULT pass=$pass fail=$fail"
