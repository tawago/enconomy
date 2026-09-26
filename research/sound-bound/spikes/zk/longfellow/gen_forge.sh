#!/bin/sh
# Test-only: derive a "forging" prover from vendor sources (Apache-2.0) that emits a
# proof even when the witness violates the circuit. The vendor prover refuses early
# and asserts on an inconsistent sumcheck; a cheater would not. Used by run_tests.sh
# to show that the VERIFIER rejects tampered statements.
# usage: gen_forge.sh <vendor lib dir> <out dir>
set -e
LF=$1; OUT=$2; mkdir -p $OUT
sed -e 's/PRIVACY_PROOFS_ZK_LIB_SUMCHECK_PROVER_LAYERS_H_/SBZK_FORGE_PROVER_LAYERS_H_/' \
    -e 's/ProverLayers/ProverLayersForge/g' \
    -e 's/^\( *\)return false;$/\1continue;  \/\/ forge: ignore violated assert0/' \
    -e 's/check(sum == expected_sum, "reconstructed sum == eq0 \* quad \* wl \* wr");/\/\/ forge: sum check removed/' \
    $LF/sumcheck/prover_layers.h > $OUT/prover_layers_forge.h
sed -e 's/PRIVACY_PROOFS_ZK_LIB_ZK_ZK_PROVER_H_/SBZK_FORGE_ZK_PROVER_H_/' \
    -e 's#"sumcheck/prover_layers.h"#"prover_layers_forge.h"#' \
    -e 's/ProverLayers/ProverLayersForge/g' -e 's/ZkProver\b/ZkProverForge/g' -e 's/class ZkProver /class ZkProverForge /' -e 's/  ZkProver(/  ZkProverForge(/' \
    -e '/V->v_\[i\] != F.zero()/{n;s/return false;/\/\/ forge: keep going/;}' \
    $LF/zk/zk_prover.h > $OUT/zk_prover_forge.h
grep -c "forge:" $OUT/prover_layers_forge.h $OUT/zk_prover_forge.h
