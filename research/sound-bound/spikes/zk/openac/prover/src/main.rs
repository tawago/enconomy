//! sbzk: prove / verify the sound-bound circom circuits with Spartan2 (ZK, Hyrax PCS on T-256),
//! the OpenAC (PSE zkID) stack. Witnesses come from the circom C++ generator linked via
//! witnesscalc-adapter (the same path zkID uses on phones).
//!
//!   sbzk setup  <circuit>                          -> keys/<circuit>.{pk,vk}
//!   sbzk check  <circuit> <input.json>             witness gen + R1CS satisfiability, no proof
//!   sbzk prove  <circuit> <input.json> <proof.bin>
//!   sbzk verify <circuit> <proof.bin> <public.json> verify + compare public IO with the expected values
//!   sbzk bench  <circuit> <input.json> <public.json> [reps]   prove+verify in one process, reps times
//!   sbzk inspect <circuit> <proof.bin>              SNARK-verify only; print the proof's public values
//!                                                  (the caller compares them: ../verifier/popzk.py)
//!
//! Circuits: sb_pair_v1, sb_pair_v2, sb_half_v1, sb_half_v2 (whichever were compiled into ../build/cpp).

use bellpepper_core::{num::AllocatedNum, ConstraintSystem, LinearCombination, SynthesisError};
use circom_scotia::{r1cs::R1CS, reader::load_r1cs};
use ff::{Field, PrimeField};
use num_bigint::BigUint;
use spartan2::{
    provider::T256HyraxEngine,
    traits::{circuit::SpartanCircuit, snark::R1CSSNARKTrait, Engine},
    zk_spartan::R1CSSNARK,
};
use std::{
    fs,
    io::{BufReader, Cursor},
    path::{Path, PathBuf},
    process::exit,
    time::Instant,
};

type E = T256HyraxEngine;
type Scalar = <E as Engine>::Scalar;
type Pk = <R1CSSNARK<E> as R1CSSNARKTrait<E>>::ProverKey;
type Vk = <R1CSSNARK<E> as R1CSSNARKTrait<E>>::VerifierKey;

#[cfg(has_sb_pair_v1)]
witnesscalc_adapter::witness!(sb_pair_v1);
#[cfg(has_sb_pair_v2)]
witnesscalc_adapter::witness!(sb_pair_v2);
#[cfg(has_sb_half_v1)]
witnesscalc_adapter::witness!(sb_half_v1);
#[cfg(has_sb_half_v2)]
witnesscalc_adapter::witness!(sb_half_v2);
#[cfg(has_popt_pair)]
witnesscalc_adapter::witness!(popt_pair);
#[cfg(has_popt_pair_nf)]
witnesscalc_adapter::witness!(popt_pair_nf);

fn witness_bytes(circuit: &str, json: &str) -> Result<Vec<u8>, String> {
    let r: anyhow_like::Res = match circuit {
        #[cfg(has_sb_pair_v1)]
        "sb_pair_v1" => sb_pair_v1_witness(json).map_err(|e| e.to_string()),
        #[cfg(has_sb_pair_v2)]
        "sb_pair_v2" => sb_pair_v2_witness(json).map_err(|e| e.to_string()),
        #[cfg(has_sb_half_v1)]
        "sb_half_v1" => sb_half_v1_witness(json).map_err(|e| e.to_string()),
        #[cfg(has_sb_half_v2)]
        "sb_half_v2" => sb_half_v2_witness(json).map_err(|e| e.to_string()),
        #[cfg(has_popt_pair)]
        "popt_pair" => popt_pair_witness(json).map_err(|e| e.to_string()),
        #[cfg(has_popt_pair_nf)]
        "popt_pair_nf" => popt_pair_nf_witness(json).map_err(|e| e.to_string()),
        _ => Err(format!("circuit {circuit} not compiled into this binary")),
    };
    r
}

mod anyhow_like {
    pub type Res = Result<Vec<u8>, String>;
}

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
}

fn r1cs_path(c: &str) -> PathBuf {
    root().join(format!("build/{c}/{c}.r1cs"))
}

fn key_paths(c: &str) -> (PathBuf, PathBuf) {
    let d = root().join("keys");
    (d.join(format!("{c}.pk")), d.join(format!("{c}.vk")))
}

/// Parse circom .wtns bytes into scalars (little-endian field elements).
fn parse_wtns(b: &[u8]) -> Vec<Scalar> {
    assert!(&b[0..4] == b"wtns", "not a wtns file");
    let n_sec = u32::from_le_bytes(b[8..12].try_into().unwrap());
    let mut pos = 12;
    let mut n8 = 0usize;
    for _ in 0..n_sec {
        let id = u32::from_le_bytes(b[pos..pos + 4].try_into().unwrap());
        let len = u64::from_le_bytes(b[pos + 4..pos + 12].try_into().unwrap()) as usize;
        pos += 12;
        if id == 1 {
            n8 = u32::from_le_bytes(b[pos..pos + 4].try_into().unwrap()) as usize;
        } else if id == 2 {
            return b[pos..pos + len]
                .chunks(n8)
                .map(|c| {
                    let mut r = <Scalar as PrimeField>::Repr::default();
                    r.as_mut()[..c.len()].copy_from_slice(c);
                    Scalar::from_repr(r).expect("witness element not canonical")
                })
                .collect();
        }
        pos += len;
    }
    panic!("no witness section");
}

fn scalar_from_dec(s: &str) -> Scalar {
    let v: BigUint = s.parse().expect("bad decimal");
    let bytes = v.to_bytes_le();
    assert!(bytes.len() <= 32, "value too large");
    let mut r = <Scalar as PrimeField>::Repr::default();
    r.as_mut()[..bytes.len()].copy_from_slice(&bytes);
    Scalar::from_repr(r).expect("value >= field modulus")
}

fn scalar_to_dec(x: &Scalar) -> String {
    BigUint::from_bytes_le(x.to_repr().as_ref()).to_string()
}

#[derive(Clone, Debug)]
struct SbCircuit {
    name: String,
    num_public: usize,
    witness: Option<Vec<Scalar>>,
}

impl SbCircuit {
    fn load_r1cs(&self) -> R1CS<Scalar> {
        load_r1cs(&r1cs_path(&self.name)).expect("load r1cs")
    }
}

/// Allocate every circom variable (public first) and all constraints.
/// Same as zkID's synthesize_all_vars (ecdsa-spartan2/src/circuits/mod.rs).
fn synthesize_r1cs<CS: ConstraintSystem<Scalar>>(
    cs: &mut CS,
    r1cs: R1CS<Scalar>,
    witness: Option<&Vec<Scalar>>,
) -> Result<(), SynthesisError> {
    let mut vars: Vec<AllocatedNum<Scalar>> = vec![];
    for i in 1..r1cs.num_inputs {
        let f = witness.map(|w| w[i]).unwrap_or(Scalar::ONE);
        vars.push(AllocatedNum::alloc_input(cs.namespace(|| format!("public_{i}")), || Ok(f))?);
    }
    for i in 0..r1cs.num_aux {
        let f = witness.map(|w| w[i + r1cs.num_inputs]).unwrap_or(Scalar::ONE);
        vars.push(AllocatedNum::alloc(cs.namespace(|| format!("aux_{i}")), || Ok(f))?);
    }
    let make_lc = |lc: &Vec<(usize, Scalar)>| {
        lc.iter().fold(LinearCombination::<Scalar>::zero(), |acc, (idx, c)| {
            acc + if *idx > 0 { (*c, vars[*idx - 1].get_variable()) } else { (*c, CS::one()) }
        })
    };
    for (i, c) in r1cs.constraints.iter().enumerate() {
        cs.enforce(|| format!("c{i}"), |_| make_lc(&c.0), |_| make_lc(&c.1), |_| make_lc(&c.2));
    }
    Ok(())
}

impl SpartanCircuit<E> for SbCircuit {
    fn public_values(&self) -> Result<Vec<Scalar>, SynthesisError> {
        Ok((1..=self.num_public)
            .map(|i| self.witness.as_ref().map(|w| w[i]).unwrap_or(Scalar::ZERO))
            .collect())
    }
    fn shared<CS: ConstraintSystem<Scalar>>(&self, _: &mut CS) -> Result<Vec<AllocatedNum<Scalar>>, SynthesisError> {
        Ok(vec![])
    }
    fn precommitted<CS: ConstraintSystem<Scalar>>(
        &self,
        _: &mut CS,
        _: &[AllocatedNum<Scalar>],
    ) -> Result<Vec<AllocatedNum<Scalar>>, SynthesisError> {
        Ok(vec![])
    }
    fn num_challenges(&self) -> usize {
        0
    }
    fn synthesize<CS: ConstraintSystem<Scalar>>(
        &self,
        cs: &mut CS,
        _: &[AllocatedNum<Scalar>],
        _: &[AllocatedNum<Scalar>],
        _: Option<&[Scalar]>,
    ) -> Result<(), SynthesisError> {
        synthesize_r1cs(cs, self.load_r1cs(), self.witness.as_ref())
    }
}

fn num_public(name: &str) -> usize {
    let r1cs = load_r1cs::<Scalar>(&r1cs_path(name)).expect("load r1cs");
    r1cs.num_inputs - 1
}

fn gen_witness(name: &str, input: &Path) -> Result<(Vec<Scalar>, u128), String> {
    let json = fs::read_to_string(input).map_err(|e| e.to_string())?;
    let t = Instant::now();
    // Run the C++ witness generator on a thread with a large stack (see README: intermittent
    // segfaults on the 8 MB main-thread stack were observed).
    let n = name.to_string();
    let wb = std::thread::Builder::new()
        .stack_size(1 << 30)
        .spawn(move || witness_bytes(&n, &json))
        .unwrap()
        .join()
        .map_err(|_| "witness thread panicked".to_string())??;
    let ms = t.elapsed().as_millis();
    Ok((parse_wtns(&wb), ms))
}

/// Direct R1CS check: every constraint <A,w>*<B,w> == <C,w>.
fn r1cs_sat(name: &str, w: &[Scalar]) -> Option<usize> {
    let r1cs = load_r1cs::<Scalar>(&r1cs_path(name)).expect("load r1cs");
    let ev = |lc: &Vec<(usize, Scalar)>| lc.iter().fold(Scalar::ZERO, |a, (i, c)| a + *c * w[*i]);
    r1cs.constraints.iter().position(|c| ev(&c.0) * ev(&c.1) != ev(&c.2))
}

fn load_pk(p: &Path) -> Pk {
    let f = fs::File::open(p).expect("open pk");
    let m = unsafe { memmap2::MmapOptions::new().map(&f).unwrap() };
    bincode::deserialize_from(Cursor::new(&m[..])).expect("decode pk")
}

fn load_vk(p: &Path) -> Vk {
    bincode::deserialize_from(BufReader::new(fs::File::open(p).expect("open vk"))).expect("decode vk")
}

fn expected_public(p: &Path) -> Vec<Scalar> {
    let v: serde_json::Value = serde_json::from_str(&fs::read_to_string(p).unwrap()).unwrap();
    v["public"].as_array().unwrap().iter().map(|x| scalar_from_dec(x.as_str().unwrap())).collect()
}

fn prove(name: &str, pk: &Pk, input: &Path) -> Result<(R1CSSNARK<E>, u128, u128), String> {
    let (w, wit_ms) = gen_witness(name, input).map_err(|e| format!("witness generation failed: {e}"))?;
    let c = SbCircuit { name: name.into(), num_public: num_public(name), witness: Some(w) };
    let t = Instant::now();
    let mut prep = R1CSSNARK::<E>::prep_prove(pk, c.clone(), false).map_err(|e| format!("prep_prove: {e:?}"))?;
    let proof = R1CSSNARK::<E>::prove(pk, c, &mut prep, false).map_err(|e| format!("prove: {e:?}"))?;
    Ok((proof, wit_ms, t.elapsed().as_millis()))
}

fn verify(vk: &Vk, proof: &R1CSSNARK<E>, expected: &[Scalar]) -> Result<u128, String> {
    let t = Instant::now();
    let got = proof.verify(vk).map_err(|e| format!("spartan verify failed: {e:?}"))?;
    let ms = t.elapsed().as_millis();
    if got.len() != expected.len() || got.iter().zip(expected).any(|(a, b)| a != b) {
        return Err(format!(
            "public IO mismatch: proof has [{}]",
            got.iter().map(scalar_to_dec).collect::<Vec<_>>().join(", ")
        ));
    }
    Ok(ms)
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    if a.len() < 3 {
        eprintln!("usage: sbzk <setup|check|prove|verify|bench> <circuit> ...");
        exit(2);
    }
    let (cmd, name) = (a[1].as_str(), a[2].as_str());
    let (pkp, vkp) = key_paths(name);
    match cmd {
        "setup" => {
            let c = SbCircuit { name: name.into(), num_public: num_public(name), witness: None };
            let t = Instant::now();
            let (pk, vk) = R1CSSNARK::<E>::setup(c).expect("setup");
            let ms = t.elapsed().as_millis();
            fs::create_dir_all(pkp.parent().unwrap()).unwrap();
            let pkb = bincode::serialize(&pk).unwrap();
            let vkb = bincode::serialize(&vk).unwrap();
            fs::write(&pkp, &pkb).unwrap();
            fs::write(&vkp, &vkb).unwrap();
            println!("RESULT setup {name} setup_ms={ms} pk_bytes={} vk_bytes={}", pkb.len(), vkb.len());
        }
        "check" => {
            let input = Path::new(&a[3]);
            match gen_witness(name, input) {
                Err(e) => {
                    println!("RESULT check {name} REJECT witness: {e}");
                    exit(1);
                }
                Ok((w, ms)) => match r1cs_sat(name, &w) {
                    None => {
                        let pubs: Vec<String> = (1..=num_public(name)).map(|i| scalar_to_dec(&w[i])).collect();
                        println!("RESULT check {name} ACCEPT witness_ms={ms} n_witness={} public=[{}]", w.len(), pubs.join(","));
                    }
                    Some(i) => {
                        println!("RESULT check {name} REJECT r1cs constraint {i} unsatisfied");
                        exit(1);
                    }
                },
            }
        }
        "prove" => {
            let t = Instant::now();
            let pk = load_pk(&pkp);
            let load_ms = t.elapsed().as_millis();
            match prove(name, &pk, Path::new(&a[3])) {
                Err(e) => {
                    println!("RESULT prove {name} REJECT {e}");
                    exit(1);
                }
                Ok((proof, wit_ms, prove_ms)) => {
                    let b = bincode::serialize(&proof).unwrap();
                    fs::write(&a[4], &b).unwrap();
                    println!(
                        "RESULT prove {name} pk_load_ms={load_ms} witness_ms={wit_ms} prove_ms={prove_ms} proof_bytes={}",
                        b.len()
                    );
                }
            }
        }
        "verify" => {
            let t = Instant::now();
            let vk = load_vk(&vkp);
            let load_ms = t.elapsed().as_millis();
            let bytes = fs::read(&a[3]).unwrap();
            let proof: R1CSSNARK<E> = match bincode::deserialize(&bytes) {
                Ok(p) => p,
                Err(e) => {
                    println!("RESULT verify {name} REJECT proof decode: {e}");
                    exit(1);
                }
            };
            match verify(&vk, &proof, &expected_public(Path::new(&a[4]))) {
                Ok(ms) => println!("RESULT verify {name} ACCEPT vk_load_ms={load_ms} verify_ms={ms}"),
                Err(e) => {
                    println!("RESULT verify {name} REJECT {e}");
                    exit(1);
                }
            }
        }
        "inspect" => {
            let t = Instant::now();
            let vk = load_vk(&vkp);
            let load_ms = t.elapsed().as_millis();
            let bytes = fs::read(&a[3]).unwrap();
            let proof: R1CSSNARK<E> = match bincode::deserialize(&bytes) {
                Ok(p) => p,
                Err(e) => {
                    println!("RESULT inspect {name} REJECT proof decode: {e}");
                    exit(1);
                }
            };
            let t = Instant::now();
            match proof.verify(&vk) {
                Ok(got) => println!(
                    "RESULT inspect {name} ACCEPT vk_load_ms={load_ms} verify_ms={} n_public={} public=[{}]",
                    t.elapsed().as_millis(),
                    got.len(),
                    got.iter().map(scalar_to_dec).collect::<Vec<_>>().join(",")
                ),
                Err(e) => {
                    println!("RESULT inspect {name} REJECT spartan verify failed: {e:?}");
                    exit(1);
                }
            }
        }
        "bench" => {
            let reps: usize = a.get(5).map(|s| s.parse().unwrap()).unwrap_or(3);
            let pk = load_pk(&pkp);
            let vk = load_vk(&vkp);
            let exp = expected_public(Path::new(&a[4]));
            for r in 0..reps {
                let (proof, wit_ms, prove_ms) = prove(name, &pk, Path::new(&a[3])).expect("prove");
                let b = bincode::serialize(&proof).unwrap();
                let vms = verify(&vk, &proof, &exp).expect("verify");
                println!(
                    "RESULT bench {name} rep={r} witness_ms={wit_ms} prove_ms={prove_ms} verify_ms={vms} proof_bytes={}",
                    b.len()
                );
            }
        }
        _ => {
            eprintln!("unknown command {cmd}");
            exit(2);
        }
    }
}
