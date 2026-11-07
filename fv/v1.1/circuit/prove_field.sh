#!/bin/bash
# Re-prove pair_named on the field witness of fixture 180ca04b_48k. Run from fv/v1.1/circuit.
# Leaves Prover.toml, out/ and vk/ of pair_named alone. Output goes to the fixture's pair/ directory.
set -euo pipefail
FX=../forge/fixtures/field_180ca04b/pair
nargo --version; bb --version
cd pair_named
cp "$FX/Prover.toml" Prover_field.toml
nargo compile
nargo execute -p Prover_field field
rm -rf vk_field
bb write_vk -b target/pair_named.json -o vk_field -t evm
cmp vk_field/vk vk/vk
cmp vk_field/vk_hash vk/vk_hash
rm -rf out_field
bb prove -b target/pair_named.json -w target/field.gz -k vk/vk -o out_field -t evm
bb verify -k vk/vk -p out_field/proof -i out_field/public_inputs -t evm
cp out_field/proof out_field/public_inputs "$FX/"
wc -c "$FX/proof" "$FX/public_inputs"
