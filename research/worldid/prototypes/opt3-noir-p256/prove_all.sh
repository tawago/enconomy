set -e
cd $S/noir
for c in half pair; do
  $S/bin/bb gates -b $c/target/$c.json 2>&1 | grep circuit_size
  rm -rf $c/vk $c/out; mkdir -p $c/vk
  $S/bin/bb write_vk -b $c/target/$c.json -o $c/vk -t evm 2>&1 | tail -1
  $S/bin/bb write_solidity_verifier -k $c/vk/vk -o $c/Verifier.sol -t evm 2>&1 | tail -1
done
for w in half halfB; do for i in 1 2 3; do mkdir -p half/out_$w
  /usr/bin/time -l $S/bin/bb prove -b half/target/half.json -w half/target/$w.gz -k half/vk/vk -o half/out_$w -t evm 2>&1 | egrep "real|maximum resident"; done; done
for i in 1 2 3; do mkdir -p pair/out
  /usr/bin/time -l $S/bin/bb prove -b pair/target/pair.json -w pair/target/pair.gz -k pair/vk/vk -o pair/out -t evm 2>&1 | egrep "real|maximum resident"; done
for d in half/out_half half/out_halfB; do $S/bin/bb verify -k half/vk/vk -p $d/proof -i $d/public_inputs -t evm 2>&1 | tail -1; done
$S/bin/bb verify -k pair/vk/vk -p pair/out/proof -i pair/out/public_inputs -t evm 2>&1 | tail -1
ls -la half/out_half pair/out half/Verifier.sol pair/Verifier.sol
