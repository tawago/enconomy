// Test-only forging prover: see gen_forge.sh. zk_prover_forge.h is generated
// at configure time from vendor lib/zk/zk_prover.h + lib/sumcheck/prover_layers.h
// with the three "refuse on bad witness" checks removed.
#ifndef SBZK_FORGE_H_
#define SBZK_FORGE_H_
#include "zk_prover_forge.h"
namespace sbzk {
template <class Field, class RSF>
using ForgingProver = proofs::ZkProverForge<Field, RSF>;
}  // namespace sbzk
#endif
