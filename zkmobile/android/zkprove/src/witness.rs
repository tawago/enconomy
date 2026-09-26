//! In-process witness generation (what `nargo execute` does), with the noir v1.0.0-beta.22 ACVM:
//! artifact JSON + Prover.toml inputs -> solved WitnessStack -> raw bytes for bbapi CircuitProve.
//! Minimal port of tooling/nargo/src/ops/execute.rs (no profiling/fuzzing); oracles: only `print`.

use acvm::acir::brillig::ForeignCallResult;
use acvm::acir::circuit::brillig::BrilligBytecode;
use acvm::acir::circuit::Circuit;
use acvm::acir::native_types::{WitnessMap, WitnessStack};
use acvm::pwg::{ACVMStatus, ACVM};
use acvm::FieldElement;
use bn254_blackbox_solver::Bn254BlackBoxSolver;
use noirc_abi::input_parser::Format;
use noirc_artifacts::program::ProgramArtifact;

use crate::Res;

struct Exec<'a> {
    functions: &'a [Circuit<FieldElement>],
    brillig: &'a [BrilligBytecode<FieldElement>],
    stack: WitnessStack<FieldElement>,
    solver: &'a Bn254BlackBoxSolver,
}

impl Exec<'_> {
    fn run(&mut self, idx: usize, initial: WitnessMap<FieldElement>) -> Res<WitnessMap<FieldElement>> {
        let c = &self.functions[idx];
        let mut acvm = ACVM::new(self.solver, &c.opcodes, initial, self.brillig, &c.assert_messages);
        loop {
            match acvm.solve() {
                ACVMStatus::Solved => break,
                ACVMStatus::InProgress => unreachable!(),
                ACVMStatus::Failure(e) => return Err(format!("acvm: function {idx}: {e}")),
                ACVMStatus::RequiresForeignCall(fc) => {
                    if fc.function != "print" {
                        return Err(format!("unsupported oracle {}", fc.function));
                    }
                    acvm.resolve_pending_foreign_call(ForeignCallResult::default());
                }
                ACVMStatus::RequiresAcirCall(call) => {
                    let id = call.id.as_usize();
                    let solved = self.run(id, call.initial_witness)?;
                    let mut outs = Vec::new();
                    for w in self.functions[id].return_values.indices() {
                        outs.push(*solved.get_index(w).ok_or(format!("missing return witness {w}"))?);
                    }
                    acvm.resolve_pending_acir_call(outs);
                    self.stack.push(call.id.0, solved);
                }
            }
        }
        Ok(acvm.finalize())
    }
}

/// Returns the raw (uncompressed) WitnessStack bytes, i.e. gunzip(nargo's target/<name>.gz).
pub fn solve(artifact_json: &[u8], prover_toml: &str) -> Res<Vec<u8>> {
    let art: ProgramArtifact = serde_json::from_slice(artifact_json).map_err(|e| format!("artifact: {e}"))?;
    let inputs = Format::Toml.parse(prover_toml, &art.abi).map_err(|e| format!("inputs: {e}"))?;
    let initial = art.abi.encode(&inputs, None).map_err(|e| format!("abi encode: {e}"))?;
    let solver = Bn254BlackBoxSolver;
    let mut ex = Exec {
        functions: &art.bytecode.functions,
        brillig: &art.bytecode.unconstrained_functions,
        stack: WitnessStack::default(),
        solver: &solver,
    };
    let main = ex.run(0, initial)?;
    ex.stack.push(0, main);
    let gz = ex.stack.serialize().map_err(|e| format!("witness serialize: {e:?}"))?;
    crate::gunzip(&gz)
}
