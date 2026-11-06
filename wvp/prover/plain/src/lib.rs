//! Plain-ABI port of openac-sdk/wasm/src/lib.rs from the pinned zkID commit.
//! Same crates, same calls, same order. Only the JS boundary differs: no
//! wasm-bindgen, just pointers plus a length-prefixed result buffer.
use ecdsa_spartan2::{
    circuit_size::CircuitSize, parse_witness, prove_circuit_in_memory, reblind_in_memory,
    PrepareCircuit, ShowCircuit,
};
use ecdsa_spartan2::{Scalar, E};
use ff::Field;
use spartan2::{traits::snark::R1CSSNARKTrait, zk_spartan::R1CSSNARK};

#[link(wasm_import_module = "openac_host")]
extern "C" {
    fn host_log(ptr: *const u8, len: usize);
}

static mut RESULT: Vec<u8> = Vec::new();

fn set_result(status: u32, parts: &[&[u8]]) -> *const u8 {
    let mut out = Vec::with_capacity(8 + parts.iter().map(|p| 4 + p.len()).sum::<usize>());
    out.extend_from_slice(&status.to_le_bytes());
    out.extend_from_slice(&(parts.len() as u32).to_le_bytes());
    for p in parts {
        out.extend_from_slice(&(p.len() as u32).to_le_bytes());
        out.extend_from_slice(p);
    }
    #[allow(static_mut_refs)]
    unsafe {
        RESULT = out;
        RESULT.as_ptr()
    }
}

#[no_mangle]
pub extern "C" fn oa_result_len() -> usize {
    #[allow(static_mut_refs)]
    unsafe { RESULT.len() }
}

#[no_mangle]
pub extern "C" fn oa_result_free() {
    #[allow(static_mut_refs)]
    unsafe { RESULT = Vec::new() }
}

#[no_mangle]
pub extern "C" fn oa_alloc(len: usize) -> *mut u8 {
    let mut v = Vec::<u8>::with_capacity(len);
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

#[no_mangle]
pub unsafe extern "C" fn oa_free(ptr: *mut u8, len: usize) {
    drop(Vec::from_raw_parts(ptr, 0, len));
}

#[no_mangle]
pub extern "C" fn oa_init() {
    std::panic::set_hook(Box::new(|info| {
        let s = info.to_string();
        unsafe { host_log(s.as_ptr(), s.len()) };
    }));
}

unsafe fn sl<'a>(p: *const u8, n: usize) -> &'a [u8] {
    std::slice::from_raw_parts(p, n)
}

fn fail(msg: String) -> *const u8 {
    set_result(1, &[msg.as_bytes()])
}

type Pk = <R1CSSNARK<E> as R1CSSNARKTrait<E>>::ProverKey;
type Vk = <R1CSSNARK<E> as R1CSSNARKTrait<E>>::VerifierKey;

macro_rules! tryf {
    ($e:expr, $m:literal) => {
        match $e {
            Ok(v) => v,
            Err(e) => return fail(format!(concat!($m, ": {:?}"), e)),
        }
    };
}

#[no_mangle]
pub unsafe extern "C" fn oa_precompute_from_witness(
    pk: *const u8, pk_n: usize, w: *const u8, w_n: usize, s: *const u8, s_n: usize,
) -> *const u8 {
    let size_str = std::str::from_utf8(sl(s, s_n)).unwrap_or("");
    let circuit_size: CircuitSize = tryf!(size_str.parse::<CircuitSize>(), "Invalid vc_size");
    let pk: Pk = tryf!(bincode::deserialize(sl(pk, pk_n)), "PK deserialization failed");
    let scalars = tryf!(parse_witness(sl(w, w_n)), "Witness parsing failed");
    let circuit = PrepareCircuit::with_witness_for_size(scalars, circuit_size);
    let (proof, instance, witness) =
        tryf!(prove_circuit_in_memory(circuit, &pk), "Prepare proving failed");
    let a = tryf!(bincode::serialize(&proof), "Proof serialization failed");
    let b = tryf!(bincode::serialize(&instance), "Instance serialization failed");
    let c = tryf!(bincode::serialize(&witness), "Witness serialization failed");
    set_result(0, &[&a, &b, &c])
}

#[no_mangle]
pub unsafe extern "C" fn oa_precompute_show_from_witness(
    pk: *const u8, pk_n: usize, w: *const u8, w_n: usize,
) -> *const u8 {
    let pk: Pk = tryf!(bincode::deserialize(sl(pk, pk_n)), "PK deserialization failed");
    let scalars = tryf!(parse_witness(sl(w, w_n)), "Witness parsing failed");
    let circuit = ShowCircuit::with_witness(scalars);
    let (proof, instance, witness) =
        tryf!(prove_circuit_in_memory(circuit, &pk), "Show proving failed");
    let a = tryf!(bincode::serialize(&proof), "Proof serialization failed");
    let b = tryf!(bincode::serialize(&instance), "Instance serialization failed");
    let c = tryf!(bincode::serialize(&witness), "Witness serialization failed");
    set_result(0, &[&a, &b, &c])
}

#[no_mangle]
pub unsafe extern "C" fn oa_present(
    ppk: *const u8, ppk_n: usize, pi: *const u8, pi_n: usize, pw: *const u8, pw_n: usize,
    spk: *const u8, spk_n: usize, si: *const u8, si_n: usize, sw: *const u8, sw_n: usize,
) -> *const u8 {
    let prepare_pk: Pk = tryf!(bincode::deserialize(sl(ppk, ppk_n)), "Prepare PK");
    let prepare_instance: spartan2::r1cs::SplitR1CSInstance<E> =
        tryf!(bincode::deserialize(sl(pi, pi_n)), "Prepare instance");
    let prepare_witness: spartan2::r1cs::R1CSWitness<E> =
        tryf!(bincode::deserialize(sl(pw, pw_n)), "Prepare witness");
    let show_pk: Pk = tryf!(bincode::deserialize(sl(spk, spk_n)), "Show PK");
    let show_instance: spartan2::r1cs::SplitR1CSInstance<E> =
        tryf!(bincode::deserialize(sl(si, si_n)), "Show instance");
    let show_witness: spartan2::r1cs::R1CSWitness<E> =
        tryf!(bincode::deserialize(sl(sw, sw_n)), "Show witness");

    let num_shared = prepare_instance.num_shared_rows();
    let shared_blinds: Vec<Scalar> = (0..num_shared)
        .map(|_| Scalar::random(&mut rand::thread_rng()))
        .collect();

    let (rp, rpi, _) = tryf!(
        reblind_in_memory(&prepare_pk, prepare_instance, prepare_witness, &shared_blinds),
        "Prepare reblind failed"
    );
    let (rs, rsi, _) = tryf!(
        reblind_in_memory(&show_pk, show_instance, show_witness, &shared_blinds),
        "Show reblind failed"
    );
    let a = tryf!(bincode::serialize(&rp), "ser");
    let b = tryf!(bincode::serialize(&rpi), "ser");
    let c = tryf!(bincode::serialize(&rs), "ser");
    let d = tryf!(bincode::serialize(&rsi), "ser");
    set_result(0, &[&a, &b, &c, &d])
}

/// status 0 = valid, parts = [prepare values joined by \n, show values joined by \n].
/// status 2 = invalid, parts = [error]. status 1 = deserialization error.
#[no_mangle]
pub unsafe extern "C" fn oa_verify(
    pp: *const u8, pp_n: usize, pvk: *const u8, pvk_n: usize, pi: *const u8, pi_n: usize,
    sp: *const u8, sp_n: usize, svk: *const u8, svk_n: usize, si: *const u8, si_n: usize,
) -> *const u8 {
    let prepare_proof: R1CSSNARK<E> = tryf!(bincode::deserialize(sl(pp, pp_n)), "Prepare proof deserialization failed");
    let prepare_vk: Vk = tryf!(bincode::deserialize(sl(pvk, pvk_n)), "Prepare VK deserialization failed");
    let _pi: spartan2::r1cs::SplitR1CSInstance<E> = tryf!(bincode::deserialize(sl(pi, pi_n)), "Prepare instance deserialization failed");
    let show_proof: R1CSSNARK<E> = tryf!(bincode::deserialize(sl(sp, sp_n)), "Show proof deserialization failed");
    let show_vk: Vk = tryf!(bincode::deserialize(sl(svk, svk_n)), "Show VK deserialization failed");
    let _si: spartan2::r1cs::SplitR1CSInstance<E> = tryf!(bincode::deserialize(sl(si, si_n)), "Show instance deserialization failed");

    let prepare_pv = match prepare_proof.verify(&prepare_vk) {
        Ok(pv) => pv,
        Err(e) => return set_result(2, &[format!("Prepare proof verification failed: {:?}", e).as_bytes()]),
    };
    let show_pv = match show_proof.verify(&show_vk) {
        Ok(pv) => pv,
        Err(e) => return set_result(2, &[format!("Show proof verification failed: {:?}", e).as_bytes()]),
    };
    let a = prepare_proof.comm_W_shared();
    let b = show_proof.comm_W_shared();
    if !(a.is_some() && b.is_some() && a == b) {
        return set_result(2, &[b"Shared commitment mismatch: prepare and show proofs do not share the same private data"]);
    }
    let ps: Vec<String> = prepare_pv.iter().map(|s| format!("{:?}", s)).collect();
    let ss: Vec<String> = show_pv.iter().map(|s| format!("{:?}", s)).collect();
    set_result(0, &[ps.join("\n").as_bytes(), ss.join("\n").as_bytes()])
}
