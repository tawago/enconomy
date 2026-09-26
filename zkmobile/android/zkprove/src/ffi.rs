//! C ABI, same shape as app/prover's pop_prover_* (return code, caller-owned buffers, `err` message).
//!   int zk_prove(circuit_json_path, inputs_toml, inputs_len, crs_path, vk_path|NULL, *proof, *public_inputs, *err)
//!   int zk_prove_witness(circuit_json_path, witness_gz, witness_len, crs_path, vk_path|NULL, *proof, *public_inputs, *err)
//!   void zk_buf_free(ZkBuf)
//! proof / public_inputs are the exact bytes `bb prove -t evm` writes (bb verify -t evm accepts them).
//! Codes: 0 ok, 1 bad argument, 2 io, 3 prove failed, 4 witness failed, 9 panic.

use crate::{bytecode_from_artifact, gunzip, init_srs, prove_raw, Res};
use std::{
    ffi::{c_char, CStr},
    panic::{catch_unwind, AssertUnwindSafe},
    ptr,
};

#[repr(C)]
pub struct ZkBuf {
    pub ptr: *mut u8,
    pub len: usize,
}

unsafe fn put(out: *mut ZkBuf, v: Vec<u8>) {
    if !out.is_null() {
        let mut b = v.into_boxed_slice();
        *out = ZkBuf { ptr: b.as_mut_ptr(), len: b.len() };
        std::mem::forget(b);
    }
}

#[no_mangle]
pub unsafe extern "C" fn zk_buf_free(b: ZkBuf) {
    if !b.ptr.is_null() {
        drop(Box::from_raw(ptr::slice_from_raw_parts_mut(b.ptr, b.len)));
    }
}

#[no_mangle]
pub extern "C" fn zk_version() -> *const c_char {
    concat!("zkprove ", env!("CARGO_PKG_VERSION"), " bb 5.0.0-nightly.20260522 ultrahonk evm\0").as_ptr() as *const c_char
}

unsafe fn path<'a>(p: *const c_char, what: &str) -> Result<&'a str, (i32, String)> {
    if p.is_null() {
        return Err((1, format!("{what} is null")));
    }
    CStr::from_ptr(p).to_str().map_err(|_| (1, format!("{what} is not UTF-8")))
}

fn io(p: &str) -> Result<Vec<u8>, (i32, String)> {
    std::fs::read(p).map_err(|e| (2, format!("{p}: {e}")))
}

fn code<T>(c: i32, r: Res<T>) -> Result<T, (i32, String)> {
    r.map_err(|m| (c, m))
}

unsafe fn guard(err: *mut ZkBuf, f: impl FnOnce() -> Result<(), (i32, String)>) -> i32 {
    let (c, m) = match catch_unwind(AssertUnwindSafe(f)) {
        Ok(Ok(())) => return 0,
        Ok(Err(e)) => e,
        Err(p) => (9, p.downcast_ref::<String>().cloned().or_else(|| p.downcast_ref::<&str>().map(|s| s.to_string())).unwrap_or("panic".into())),
    };
    put(err, m.into_bytes());
    c
}

unsafe fn common(
    circuit: *const c_char,
    crs: *const c_char,
    vk: *const c_char,
    witness: impl FnOnce(&[u8]) -> Result<Vec<u8>, (i32, String)>,
    proof: *mut ZkBuf,
    pubs: *mut ZkBuf,
) -> Result<(), (i32, String)> {
    let art = io(path(circuit, "circuit_json_path")?)?;
    let acir = code(1, bytecode_from_artifact(&art))?;
    let w = witness(&art)?;
    drop(art);
    {
        let g1 = io(path(crs, "crs_path")?)?;
        code(1, init_srs(&g1, 1 << 20))?;
    }
    let vk = if vk.is_null() { vec![] } else { io(path(vk, "vk_path")?)? };
    let p = code(3, prove_raw(acir, &w, vk))?;
    put(proof, p.proof);
    put(pubs, p.public_inputs);
    Ok(())
}

/// Prove from a laptop/server-made witness (nargo execute output, gzipped WitnessStack).
#[no_mangle]
pub unsafe extern "C" fn zk_prove_witness(
    circuit_json_path: *const c_char,
    witness_gz: *const u8,
    witness_len: usize,
    crs_path: *const c_char,
    vk_path: *const c_char,
    proof: *mut ZkBuf,
    public_inputs: *mut ZkBuf,
    err: *mut ZkBuf,
) -> i32 {
    guard(err, || {
        if witness_gz.is_null() {
            return Err((1, "witness is null".into()));
        }
        let w = std::slice::from_raw_parts(witness_gz, witness_len);
        common(circuit_json_path, crs_path, vk_path, |_| code(1, gunzip(w)), proof, public_inputs)
    })
}

/// Whole thing on the phone: ACVM witness from Prover.toml-style inputs, then prove.
#[cfg(feature = "witness")]
#[no_mangle]
pub unsafe extern "C" fn zk_prove(
    circuit_json_path: *const c_char,
    inputs_toml: *const u8,
    inputs_len: usize,
    crs_path: *const c_char,
    vk_path: *const c_char,
    proof: *mut ZkBuf,
    public_inputs: *mut ZkBuf,
    err: *mut ZkBuf,
) -> i32 {
    guard(err, || {
        if inputs_toml.is_null() {
            return Err((1, "inputs is null".into()));
        }
        let t = std::str::from_utf8(std::slice::from_raw_parts(inputs_toml, inputs_len)).map_err(|_| (1, "inputs not UTF-8".to_string()))?;
        common(circuit_json_path, crs_path, vk_path, |art| code(4, crate::witness::solve(art, t)), proof, public_inputs)
    })
}
