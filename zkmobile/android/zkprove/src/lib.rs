//! UltraHonk (evm target: keccak transcript, ZK) prover for the optA-noir `phone` circuit, linked
//! against the Barretenberg static lib (v5.0.0-nightly.20260522, same build as the ZK team's bb CLI).
//! Proof / public_inputs bytes are laid out exactly like `bb prove -t evm` output files
//! (concatenated 32-byte big-endian fields), so `bb verify -k vk -t evm` checks them.

use barretenberg_rs::backends::FfiBackend;
use barretenberg_rs::generated_types::{CircuitInput, ProofSystemSettings};
use barretenberg_rs::BarretenbergApi;
use std::io::Read;
use std::sync::Once;

#[cfg(feature = "witness")]
pub mod witness;
pub mod ffi;

/// Canonical Aztec BN254 [x]_2 (srs/factories/bn254_crs_data.hpp, BN254_G2_ELEMENT_BYTES).
pub const G2: [u8; 128] = [
    0x01, 0x18, 0xc4, 0xd5, 0xb8, 0x37, 0xbc, 0xc2, 0xbc, 0x89, 0xb5, 0xb3, 0x98, 0xb5, 0x97, 0x4e, 0x9f, 0x59, 0x44,
    0x07, 0x3b, 0x32, 0x07, 0x8b, 0x7e, 0x23, 0x1f, 0xec, 0x93, 0x88, 0x83, 0xb0, 0x26, 0x0e, 0x01, 0xb2, 0x51, 0xf6,
    0xf1, 0xc7, 0xe7, 0xff, 0x4e, 0x58, 0x07, 0x91, 0xde, 0xe8, 0xea, 0x51, 0xd8, 0x7a, 0x35, 0x8e, 0x03, 0x8b, 0x4e,
    0xfe, 0x30, 0xfa, 0xc0, 0x93, 0x83, 0xc1, 0x22, 0xfe, 0xbd, 0xa3, 0xc0, 0xc0, 0x63, 0x2a, 0x56, 0x47, 0x5b, 0x42,
    0x14, 0xe5, 0x61, 0x5e, 0x11, 0xe6, 0xdd, 0x3f, 0x96, 0xe6, 0xce, 0xa2, 0x85, 0x4a, 0x87, 0xd4, 0xda, 0xcc, 0x5e,
    0x55, 0x04, 0xfc, 0x63, 0x69, 0xf7, 0x11, 0x0f, 0xe3, 0xd2, 0x51, 0x56, 0xc1, 0xbb, 0x9a, 0x72, 0x85, 0x9c, 0xf2,
    0xa0, 0x46, 0x41, 0xf9, 0x9b, 0xa4, 0xee, 0x41, 0x3c, 0x80, 0xda, 0x6a, 0x5f, 0xe4,
];

#[cfg(target_os = "android")]
extern "C" {
    fn zk_tls_align_ref() -> *mut u8;
}

/// Keeps the 64-aligned TLS object (src/tls_align.c) linked in.
#[cfg(target_os = "android")]
#[used]
static TLS_ALIGN_KEEP: unsafe extern "C" fn() -> *mut u8 = zk_tls_align_ref;

pub type Res<T> = std::result::Result<T, String>;

pub fn gunzip(b: &[u8]) -> Res<Vec<u8>> {
    let mut out = Vec::new();
    flate2::read::GzDecoder::new(b).read_to_end(&mut out).map_err(|e| format!("gunzip: {e}"))?;
    Ok(out)
}

/// nargo artifact JSON -> raw (uncompressed) ACIR program bytes, like bb's get_bytecode_from_json.
pub fn bytecode_from_artifact(json: &[u8]) -> Res<Vec<u8>> {
    let v: serde_json::Value = serde_json::from_slice(json).map_err(|e| format!("artifact json: {e}"))?;
    let b64 = v["bytecode"].as_str().ok_or("artifact has no bytecode")?;
    use base64::Engine;
    let gz = base64::engine::general_purpose::STANDARD.decode(b64).map_err(|e| format!("base64: {e}"))?;
    gunzip(&gz)
}

pub struct Proof {
    pub proof: Vec<u8>,
    pub public_inputs: Vec<u8>,
}

static SRS: Once = Once::new();

fn api() -> BarretenbergApi<FfiBackend> {
    BarretenbergApi::new(FfiBackend::new().expect("ffi backend"))
}

/// Load the BN254 SRS (uncompressed 64-byte points, i.e. ~/.bb-crs/bn254_g1.dat) once per process.
pub fn init_srs(g1: &[u8], num_points: u32) -> Res<()> {
    let mut err = None;
    SRS.call_once(|| {
        let n = num_points.min((g1.len() / 64) as u32);
        if let Err(e) = api().srs_init_srs(&g1[..n as usize * 64], n, &G2) {
            err = Some(format!("srs init: {e}"));
        }
    });
    err.map_or(Ok(()), Err)
}

fn settings() -> ProofSystemSettings {
    // bb CLI `-t evm` => oracle_hash_type keccak, zk on, no IPA
    ProofSystemSettings {
        ipa_accumulation: false,
        oracle_hash_type: "keccak".into(),
        disable_zk: false,
        optimized_solidity_verifier: false,
    }
}

/// acir: raw ACIR program bytes; witness: raw (gunzipped) WitnessStack bytes; vk: optional bb vk bytes.
pub fn prove_raw(acir: Vec<u8>, witness: &[u8], vk: Vec<u8>) -> Res<Proof> {
    let circuit = CircuitInput { name: "phone".into(), bytecode: acir, verification_key: vk };
    let r = api().circuit_prove(circuit, witness, settings()).map_err(|e| format!("prove: {e}"))?;
    let cat = |v: &Vec<Vec<u8>>| -> Vec<u8> {
        let mut o = Vec::with_capacity(v.len() * 32);
        for f in v {
            o.extend(std::iter::repeat(0u8).take(32usize.saturating_sub(f.len())));
            o.extend_from_slice(f);
        }
        o
    };
    Ok(Proof { proof: cat(&r.proof), public_inputs: cat(&r.public_inputs) })
}

/// Peak resident set of this process in kB (VmHWM), Linux/Android only.
pub fn vm_hwm_kb() -> u64 {
    std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|s| {
            s.lines()
                .find(|l| l.starts_with("VmHWM"))
                .and_then(|l| l.split_whitespace().nth(1).and_then(|x| x.parse().ok()))
        })
        .unwrap_or(0)
}
