#!/bin/bash
# Phone A, phone B, pair_named on the patched witnesses in ./work. Run from fv/v1.1/circuit/frame_tx on the prover machine.
# Needs research/worldid/prototypes/optA-noir/noir/{phone,oalib} synced and phone compiled once. Output in ./out.
set -euo pipefail
HERE=$(pwd)
PH=$HERE/../../../../research/worldid/prototypes/optA-noir/noir/phone
PN=$HERE/../pair_named
PHONE_VK_HASH=2991b4b80fba7cab1645dd154c75dfb0a9440f9c3f582d5df967b11b7c311aba
rm -rf out; mkdir -p out/A out/B out/pair

cd "$PH"
[ -f target/phone.json ] || nargo compile
rm -rf vk_frame
bb write_vk -b target/phone.json -o vk_frame -t evm
[ "$(xxd -p -c 64 vk_frame/vk_hash)" = "$PHONE_VK_HASH" ]
for r in A B; do
  cp "$HERE/work/$r.toml" "Prover_frame$r.toml"
  nargo execute -p "Prover_frame$r" "frame$r"
  rm -rf "out_frame$r"
  bb prove -b target/phone.json -w "target/frame$r.gz" -k vk_frame/vk -o "out_frame$r" -t evm
  bb verify -k vk_frame/vk -p "out_frame$r/proof" -i "out_frame$r/public_inputs" -t evm
  cp "out_frame$r/proof" "out_frame$r/public_inputs" "$HERE/out/$r/"
done

# commit_a, commit_b are word 11 of the phone proofs.
word11() { python3 -c "import sys;print(int.from_bytes(open(sys.argv[1],'rb').read()[11*32:12*32],'big'))" "$1"; }
ca=$(word11 "$HERE/out/A/public_inputs")
cb=$(word11 "$HERE/out/B/public_inputs")
cd "$PN"
sed -e "s/^commit_a = .*/commit_a = \"$ca\"/" -e "s/^commit_b = .*/commit_b = \"$cb\"/" "$HERE/work/pair.toml" > Prover_frame.toml
cp Prover_frame.toml "$HERE/out/pair/Prover.toml"
nargo compile
nargo execute -p Prover_frame frame
rm -rf vk_frame out_frame
bb write_vk -b target/pair_named.json -o vk_frame -t evm
cmp vk_frame/vk vk/vk
bb prove -b target/pair_named.json -w target/frame.gz -k vk/vk -o out_frame -t evm
bb verify -k vk/vk -p out_frame/proof -i out_frame/public_inputs -t evm
cp out_frame/proof out_frame/public_inputs "$HERE/out/pair/"
wc -c "$HERE"/out/*/proof "$HERE"/out/*/public_inputs
