//! Option A per-phone prover for POPT v2 (circuits oa2t_s48 / oa2t_s44).
//! Port of research/sound-bound/spikes/zk/optionA-v2/prover (oa2zk): circom C++ witness via witnesscalc,
//! zkID Spartan2 (Hyrax on T-256) proof. Differences from the spike binary:
//!   - no .r1cs at runtime: the proving key carries the R1CS shape; synthesis only allocates variables
//!     (Spartan2's SatisfyingAssignment ignores constraints anyway) and the circuit is told apart by
//!     its public-input count,
//!   - `check` evaluates every constraint against the key's shape before proving (the prover itself
//!     happily turns a bad witness into a proof that fails verification).
//! C ABI in `ffi` (include/pop_prover.h); JNI wrappers in `jni_android`.

use bellpepper_core::{num::AllocatedNum, ConstraintSystem, SynthesisError};
use ff::{Field, PrimeField};
use num_bigint::BigUint;
use spartan2::{
    provider::T256HyraxEngine,
    traits::{circuit::SpartanCircuit, snark::R1CSSNARKTrait, Engine},
    zk_spartan::R1CSSNARK,
};
use std::{fmt, fs, io::Cursor, path::Path, time::Instant};

pub mod ffi;
#[cfg(target_os = "android")]
mod jni_android;

type E = T256HyraxEngine;
pub type Scalar = <E as Engine>::Scalar;
type Pk = <R1CSSNARK<E> as R1CSSNARKTrait<E>>::ProverKey;
type Vk = <R1CSSNARK<E> as R1CSSNARKTrait<E>>::VerifierKey;

/// Blinding variables zk_spartan appends to the witness (spartan2 bellpepper/zk_r1cs.rs NUM_BLINDS).
const NUM_BLINDS: usize = 4;
/// Witness generation runs on its own thread: the spike saw segfaults on the 8 MB main stack.
const WITNESS_STACK: usize = 512 << 20;

#[cfg(has_oa2t_s48)]
witnesscalc_adapter::witness!(oa2t_s48);
#[cfg(has_oa2t_s44)]
witnesscalc_adapter::witness!(oa2t_s44);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Circuit {
    S48,
    S44,
}

impl Circuit {
    pub fn name(self) -> &'static str {
        match self {
            Circuit::S48 => "oa2t_s48",
            Circuit::S44 => "oa2t_s44",
        }
    }
    pub fn sample_rate(self) -> u32 {
        match self {
            Circuit::S48 => 48000,
            Circuit::S44 => 44100,
        }
    }
    /// Public vector length: halfCommit, 6 header values, 4 templates of L, issuer x/y, sr, validAt.
    pub fn num_public(self) -> usize {
        let l = match self {
            Circuit::S48 => 12000,
            Circuit::S44 => 11025,
        };
        1 + 6 + 4 * l + 4
    }
    pub fn from_name(s: &str) -> Option<Self> {
        match s {
            "oa2t_s48" => Some(Circuit::S48),
            "oa2t_s44" => Some(Circuit::S44),
            _ => None,
        }
    }
    fn from_num_public(n: usize) -> Option<Self> {
        [Circuit::S48, Circuit::S44].into_iter().find(|c| c.num_public() == n)
    }
    fn witness_bytes(self, json: &str) -> Result<Vec<u8>, String> {
        match self {
            #[cfg(has_oa2t_s48)]
            Circuit::S48 => oa2t_s48_witness(json).map_err(|e| e.to_string()),
            #[cfg(has_oa2t_s44)]
            Circuit::S44 => oa2t_s44_witness(json).map_err(|e| e.to_string()),
            #[allow(unreachable_patterns)]
            _ => Err(format!("{} not compiled in", self.name())),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum Code {
    Ok = 0,
    Arg = 1,
    Io = 2,
    Witness = 3,
    Unsat = 4,
    Prove = 5,
    Verify = 6,
    Panic = 7,
}

#[derive(Debug)]
pub struct Error {
    pub code: Code,
    pub msg: String,
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}: {}", self.code, self.msg)
    }
}

fn err<T>(code: Code, msg: impl Into<String>) -> Result<T, Error> {
    Err(Error { code, msg: msg.into() })
}

pub type Res<T> = Result<T, Error>;

pub fn scalar_to_dec(x: &Scalar) -> String {
    BigUint::from_bytes_le(x.to_repr().as_ref()).to_string()
}

pub fn scalar_from_dec(s: &str) -> Res<Scalar> {
    let v: BigUint = s.parse().map_err(|_| Error { code: Code::Arg, msg: format!("bad decimal {s:?}") })?;
    let b = v.to_bytes_le();
    if b.len() > 32 {
        return err(Code::Arg, "value too large");
    }
    let mut r = <Scalar as PrimeField>::Repr::default();
    r.as_mut()[..b.len()].copy_from_slice(&b);
    Option::from(Scalar::from_repr(r)).ok_or(Error { code: Code::Arg, msg: "value >= field modulus".into() })
}

/// circom .wtns bytes -> field elements (little endian, n8 = 32).
pub fn parse_wtns(b: &[u8]) -> Res<Vec<Scalar>> {
    let bad = || Error { code: Code::Witness, msg: "malformed wtns".into() };
    let u32at = |p: usize| b.get(p..p + 4).map(|s| u32::from_le_bytes(s.try_into().unwrap()));
    if b.get(0..4) != Some(b"wtns") {
        return Err(bad());
    }
    let n_sec = u32at(8).ok_or_else(bad)?;
    let (mut pos, mut n8) = (12usize, 0usize);
    for _ in 0..n_sec {
        let id = u32at(pos).ok_or_else(bad)?;
        let len = b.get(pos + 4..pos + 12).map(|s| u64::from_le_bytes(s.try_into().unwrap())).ok_or_else(bad)? as usize;
        pos += 12;
        if id == 1 {
            n8 = u32at(pos).ok_or_else(bad)? as usize;
        } else if id == 2 {
            if n8 == 0 || n8 > 32 {
                return Err(bad());
            }
            let sec = b.get(pos..pos + len).ok_or_else(bad)?;
            return sec
                .chunks(n8)
                .map(|c| {
                    let mut r = <Scalar as PrimeField>::Repr::default();
                    r.as_mut()[..c.len()].copy_from_slice(c);
                    Option::from(Scalar::from_repr(r)).ok_or_else(bad)
                })
                .collect();
        }
        pos += len;
    }
    Err(bad())
}

const ZSTD_MAGIC: [u8; 4] = [0x28, 0xb5, 0x2f, 0xfd];

/// bincode key file, plain (mmap) or zstd-compressed (streamed, never inflated on disk).
fn read_key<T: serde::de::DeserializeOwned>(p: &Path, what: &str) -> Res<T> {
    let io = |e: std::io::Error| Error { code: Code::Io, msg: format!("{what} {}: {e}", p.display()) };
    let de = |e: bincode::Error| Error { code: Code::Io, msg: format!("decode {what}: {e}") };
    let f = fs::File::open(p).map_err(io)?;
    let m = unsafe { memmap2::MmapOptions::new().map(&f) }.map_err(io)?;
    if m.len() >= 4 && m[..4] == ZSTD_MAGIC {
        let d = zstd::stream::read::Decoder::with_buffer(&m[..]).map_err(io)?;
        bincode::deserialize_from(std::io::BufReader::with_capacity(1 << 20, d)).map_err(de)
    } else {
        bincode::deserialize_from(Cursor::new(&m[..])).map_err(de)
    }
}

/// All circom variables, allocated with the witness values and no constraints: in `prove` Spartan2
/// only reads the assignment; the constraint system lives in the key (`pk.S`).
#[derive(Clone)]
struct Assigned<'a> {
    num_public: usize,
    num_aux: usize,
    w: &'a [Scalar],
}

impl SpartanCircuit<E> for Assigned<'_> {
    fn public_values(&self) -> Result<Vec<Scalar>, SynthesisError> {
        Ok(self.w[1..=self.num_public].to_vec())
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
        for i in 1..=self.num_public {
            AllocatedNum::alloc_input(cs.namespace(|| format!("public_{i}")), || Ok(self.w[i]))?;
        }
        let off = 1 + self.num_public;
        for i in 0..self.num_aux {
            AllocatedNum::alloc(cs.namespace(|| format!("aux_{i}")), || Ok(self.w[off + i]))?;
        }
        Ok(())
    }
}

pub struct Timings {
    pub witness_ms: u128,
    pub check_ms: u128,
    pub prove_ms: u128,
}

pub struct Prover {
    pub circuit: Circuit,
    pk: Pk,
    num_public: usize,
    num_aux: usize,
    pub load_ms: u128,
}

impl Prover {
    /// Loads a proving key (bincode, as written by the spike's `oa2zk setup`) and identifies the circuit.
    pub fn load(pk_path: &Path) -> Res<Self> {
        let t = Instant::now();
        let pk: Pk = read_key(pk_path, "pk")?;
        // [cons_u, shared_u, precommitted_u, rest_u, cons, shared, precommitted, rest, public, challenges]
        let s = pk.sizes();
        if s[1] != 0 || s[2] != 0 || s[9] != 0 || s[3] < NUM_BLINDS {
            return err(Code::Arg, format!("unexpected key shape {s:?}"));
        }
        let circuit = Circuit::from_num_public(s[8]).ok_or(Error { code: Code::Arg, msg: format!("unknown circuit, {} public inputs", s[8]) })?;
        Ok(Prover { circuit, pk, num_public: s[8], num_aux: s[3] - NUM_BLINDS, load_ms: t.elapsed().as_millis() })
    }

    /// circom witness [1, public.., aux..] from the input JSON (prep_popt2.py layout).
    pub fn witness(&self, json: &str) -> Res<Vec<Scalar>> {
        let (c, j) = (self.circuit, json.to_string());
        let wb = std::thread::Builder::new()
            .stack_size(WITNESS_STACK)
            .spawn(move || c.witness_bytes(&j))
            .map_err(|e| Error { code: Code::Witness, msg: format!("spawn: {e}") })?
            .join()
            .map_err(|_| Error { code: Code::Panic, msg: "witness thread panicked".into() })?
            .map_err(|e| Error { code: Code::Witness, msg: e })?;
        let w = parse_wtns(&wb)?;
        if w.len() != 1 + self.num_public + self.num_aux {
            return err(
                Code::Witness,
                format!("witness has {} values, key expects {}", w.len(), 1 + self.num_public + self.num_aux),
            );
        }
        if w[0] != Scalar::ONE {
            return err(Code::Witness, "witness[0] != 1");
        }
        Ok(w)
    }

    /// Every constraint A·z ∘ B·z == C·z of the key's R1CS; returns the public values on success.
    /// z = [aux, blinds (0), padding (0), 1, public] (spartan2 SplitR1CSShape layout, no shared/precommitted).
    pub fn check(&self, w: &[Scalar]) -> Res<Vec<Scalar>> {
        let s = self.pk.sizes();
        let (rest, cons_u) = (s[7], s[0]);
        let mut z = Vec::with_capacity(rest + 1 + self.num_public);
        z.extend_from_slice(&w[1 + self.num_public..]);
        z.resize(rest, Scalar::ZERO);
        z.push(Scalar::ONE);
        z.extend_from_slice(&w[1..=self.num_public]);
        let (a, b, c) = self.pk.S.multiply_vec(&z).map_err(|e| Error { code: Code::Unsat, msg: format!("{e:?}") })?;
        if let Some(i) = (0..a.len()).find(|&i| a[i] * b[i] != c[i]) {
            let tag = if i >= cons_u { " (padding/blinding row)" } else { "" };
            return err(Code::Unsat, format!("constraint {i}{tag} unsatisfied"));
        }
        Ok(w[1..=self.num_public].to_vec())
    }

    /// witness -> check -> prove. Never proves a witness that fails `check`.
    pub fn prove(&self, json: &str) -> Res<(Vec<u8>, Vec<Scalar>, Timings)> {
        let t = Instant::now();
        let w = self.witness(json)?;
        let witness_ms = t.elapsed().as_millis();
        let t = Instant::now();
        let public = self.check(&w)?;
        let check_ms = t.elapsed().as_millis();
        let t = Instant::now();
        let circ = Assigned { num_public: self.num_public, num_aux: self.num_aux, w: &w };
        let perr = |e: spartan2::errors::SpartanError| Error { code: Code::Prove, msg: format!("{e:?}") };
        let prep = R1CSSNARK::<E>::prep_prove(&self.pk, circ.clone(), false).map_err(perr)?;
        let proof = R1CSSNARK::<E>::prove(&self.pk, circ, &prep, false).map_err(perr)?;
        let bytes = bincode::serialize(&proof).map_err(|e| Error { code: Code::Prove, msg: e.to_string() })?;
        Ok((bytes, public, Timings { witness_ms, check_ms, prove_ms: t.elapsed().as_millis() }))
    }
}

pub struct Verifier {
    vk: Vk,
}

impl Verifier {
    pub fn load(vk_path: &Path) -> Res<Self> {
        Ok(Verifier { vk: read_key(vk_path, "vk")? })
    }

    /// SNARK verify; returns the proof's public values. With `expected`, they must match exactly.
    pub fn verify(&self, proof: &[u8], expected: Option<&[Scalar]>) -> Res<Vec<Scalar>> {
        let p: R1CSSNARK<E> = bincode::deserialize(proof).map_err(|e| Error { code: Code::Verify, msg: format!("decode proof: {e}") })?;
        let got = p.verify(&self.vk).map_err(|e| Error { code: Code::Verify, msg: format!("{e:?}") })?;
        if let Some(x) = expected {
            if x.len() != got.len() {
                return err(Code::Verify, format!("public length {} != expected {}", got.len(), x.len()));
            }
            if let Some(i) = (0..x.len()).find(|&i| x[i] != got[i]) {
                return err(Code::Verify, format!("public[{i}] mismatch"));
            }
        }
        Ok(got)
    }
}

/// {"public": ["dec", ...]} (spike public.json layout).
pub fn public_to_json(p: &[Scalar]) -> String {
    serde_json::json!({ "public": p.iter().map(scalar_to_dec).collect::<Vec<_>>() }).to_string()
}

pub fn public_from_json(s: &str) -> Res<Vec<Scalar>> {
    let v: serde_json::Value = serde_json::from_str(s).map_err(|e| Error { code: Code::Arg, msg: format!("public json: {e}") })?;
    let a = v.get("public").and_then(|a| a.as_array()).or_else(|| v.as_array());
    let a = a.ok_or(Error { code: Code::Arg, msg: "public json: expected {\"public\": [...]}".into() })?;
    a.iter()
        .map(|x| x.as_str().ok_or(Error { code: Code::Arg, msg: "public values must be decimal strings".into() }).and_then(scalar_from_dec))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dec_roundtrip() {
        let p = "115792089210356248762697446949407573530086143415290314195533631308867097853951";
        assert!(scalar_from_dec(p).is_err(), "p itself is out of range");
        let m1 = "115792089210356248762697446949407573530086143415290314195533631308867097853950";
        let x = scalar_from_dec(m1).unwrap();
        assert_eq!(x, -Scalar::ONE);
        assert_eq!(scalar_to_dec(&x), m1);
        assert_eq!(scalar_to_dec(&scalar_from_dec("0").unwrap()), "0");
    }

    #[test]
    fn public_json_roundtrip() {
        let v = vec![Scalar::from(7u64), -Scalar::ONE];
        assert_eq!(public_from_json(&public_to_json(&v)).unwrap(), v);
        assert!(public_from_json("{\"public\": [1]}").is_err());
    }

    #[test]
    fn wtns_parse() {
        let mut b = b"wtns".to_vec();
        b.extend(2u32.to_le_bytes());
        b.extend(2u32.to_le_bytes());
        b.extend(1u32.to_le_bytes());
        b.extend(40u64.to_le_bytes());
        b.extend(32u32.to_le_bytes());
        b.extend([0u8; 32]);
        b.extend(2u32.to_le_bytes());
        b.extend(2u32.to_le_bytes());
        b.extend(64u64.to_le_bytes());
        let mut one = [0u8; 32];
        one[0] = 1;
        b.extend(one);
        let mut five = [0u8; 32];
        five[0] = 5;
        b.extend(five);
        assert_eq!(parse_wtns(&b).unwrap(), vec![Scalar::ONE, Scalar::from(5u64)]);
        assert!(parse_wtns(&b[..b.len() - 1]).is_err());
        assert!(parse_wtns(b"nope").is_err());
    }

    #[test]
    fn circuits() {
        assert_eq!(Circuit::S48.num_public(), 48011);
        assert_eq!(Circuit::S44.num_public(), 44111);
        assert_eq!(Circuit::from_num_public(44111), Some(Circuit::S44));
        assert_eq!(Circuit::from_name("oa2t_s48"), Some(Circuit::S48));
    }

    #[test]
    fn missing_key() {
        let e = Prover::load(Path::new("/nonexistent.pk")).err().unwrap();
        assert_eq!(e.code, Code::Io);
    }
}
