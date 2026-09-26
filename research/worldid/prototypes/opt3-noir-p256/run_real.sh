# usage: run_real.sh FIXTURE_NAME [extra gen_real args]; outputs in $S/runs/NAME$TAG
S=/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/onchain-zk/opt3-nonnative-p256
F=/Users/takahiro_ogawa/dev/enconomy/research/sound-bound/spikes/zk/fixtures/popt_v2
G=/Users/takahiro_ogawa/dev/enconomy/research/worldid/prototypes/opt3-noir-p256/noir/gen_real.py
export NARGO=$S/bin/nargo; BB=$S/bin/bb; n=$1; shift; R=$S/runs/$n$TAG; rm -rf $R; mkdir -p $R/half $R/pair
python3 $G $F/$n.json $S/noir --cred bn --lows "$@" || exit 1
cd $S/noir/half
for w in half halfB; do p=Prover; [ $w = halfB ] && p=ProverB
  if $NARGO execute -p $p $w >/tmp/null 2>$R/$w.exec.err; then echo "$w execute OK"
    mkdir -p $R/half/r_$w; $BB prove -b target/half.json -w target/$w.gz -k vk/vk -o $R/half/r_$w -t evm >/dev/null 2>&1 && echo "$w prove OK" || echo "$w prove FAIL"
    $BB verify -k vk/vk -p $R/half/r_$w/proof -i $R/half/r_$w/public_inputs -t evm 2>&1 | tail -1
  else echo "$w execute FAIL: $(grep -m1 -o 'lib.nr:[0-9]*\|main.nr:[0-9]*' $R/$w.exec.err) $(grep -m1 Failed $R/$w.exec.err)"; fi; done
cd $S/noir/pair
if $NARGO execute pair >/dev/null 2>$R/pair.exec.err; then echo "pair execute OK"
  mkdir -p $R/pair/r_out; $BB prove -b target/pair.json -w target/pair.gz -k vk/vk -o $R/pair/r_out -t evm >/dev/null 2>&1 && echo "pair prove OK"
  $BB verify -k vk/vk -p $R/pair/r_out/proof -i $R/pair/r_out/public_inputs -t evm 2>&1 | tail -1
else echo "pair execute FAIL: $(grep -m1 -o 'lib.nr:[0-9]*\|main.nr:[0-9]*' $R/pair.exec.err) $(grep -m1 Failed $R/pair.exec.err)"; fi
