//! C ABI (include/pop_prover.h). Every call returns a PopCode; on failure `err` (if non-null) gets a
//! UTF-8 message. Buffers handed out are owned by the caller and released with pop_buf_free.

use crate::{public_from_json, public_to_json, Code, Error, Prover, Res, Verifier};
use std::{
    ffi::{c_char, CStr},
    panic::{catch_unwind, AssertUnwindSafe},
    path::Path,
    ptr,
};

#[repr(C)]
pub struct PopBuf {
    pub ptr: *mut u8,
    pub len: usize,
}

impl PopBuf {
    fn from_vec(v: Vec<u8>) -> PopBuf {
        let mut b = v.into_boxed_slice();
        let r = PopBuf { ptr: b.as_mut_ptr(), len: b.len() };
        std::mem::forget(b);
        r
    }
}

unsafe fn put(out: *mut PopBuf, v: Vec<u8>) {
    if !out.is_null() {
        *out = PopBuf::from_vec(v);
    }
}

unsafe fn cstr<'a>(p: *const c_char, what: &str) -> Res<&'a str> {
    if p.is_null() {
        return Err(Error { code: Code::Arg, msg: format!("{what} is null") });
    }
    CStr::from_ptr(p).to_str().map_err(|_| Error { code: Code::Arg, msg: format!("{what} is not UTF-8") })
}

unsafe fn bytes<'a>(p: *const u8, n: usize, what: &str) -> Res<&'a [u8]> {
    if p.is_null() {
        return Err(Error { code: Code::Arg, msg: format!("{what} is null") });
    }
    Ok(std::slice::from_raw_parts(p, n))
}

unsafe fn text<'a>(p: *const u8, n: usize, what: &str) -> Res<&'a str> {
    std::str::from_utf8(bytes(p, n, what)?).map_err(|_| Error { code: Code::Arg, msg: format!("{what} is not UTF-8") })
}

/// Runs f, maps errors and panics to a code, writes the message to `err`.
unsafe fn guard(err: *mut PopBuf, f: impl FnOnce() -> Res<()>) -> i32 {
    let e = match catch_unwind(AssertUnwindSafe(f)) {
        Ok(Ok(())) => return Code::Ok as i32,
        Ok(Err(e)) => e,
        Err(p) => {
            let msg = p.downcast_ref::<String>().cloned().or_else(|| p.downcast_ref::<&str>().map(|s| s.to_string()));
            Error { code: Code::Panic, msg: msg.unwrap_or_else(|| "panic".into()) }
        }
    };
    put(err, e.msg.into_bytes());
    e.code as i32
}

#[no_mangle]
pub unsafe extern "C" fn pop_buf_free(b: PopBuf) {
    if !b.ptr.is_null() {
        drop(Box::from_raw(ptr::slice_from_raw_parts_mut(b.ptr, b.len)));
    }
}

#[no_mangle]
pub extern "C" fn pop_prover_version() -> *const c_char {
    concat!("pop-prover ", env!("CARGO_PKG_VERSION"), " spartan2@d687dbb t256-hyrax\0").as_ptr() as *const c_char
}

/// Loads the proving key (~0.45 GB file, ~2 GB peak while proving). *out gets the handle.
#[no_mangle]
pub unsafe extern "C" fn pop_prover_open(pk_path: *const c_char, out: *mut *mut Prover, err: *mut PopBuf) -> i32 {
    guard(err, || {
        if out.is_null() {
            return Err(Error { code: Code::Arg, msg: "out is null".into() });
        }
        let p = Prover::load(Path::new(cstr(pk_path, "pk_path")?))?;
        *out = Box::into_raw(Box::new(p));
        Ok(())
    })
}

#[no_mangle]
pub unsafe extern "C" fn pop_prover_close(p: *mut Prover) {
    if !p.is_null() {
        drop(Box::from_raw(p));
    }
}

/// Circuit sample rate of an open prover (48000 or 44100), 0 on null.
#[no_mangle]
pub unsafe extern "C" fn pop_prover_sample_rate(p: *const Prover) -> u32 {
    p.as_ref().map(|p| p.circuit.sample_rate()).unwrap_or(0)
}

fn handle<'a>(p: *const Prover) -> Res<&'a Prover> {
    unsafe { p.as_ref() }.ok_or(Error { code: Code::Arg, msg: "prover is null".into() })
}

/// Witness + full constraint check, no proof. public_json (optional) gets {"public": [...]}.
#[no_mangle]
pub unsafe extern "C" fn pop_prover_check(
    p: *const Prover,
    input_json: *const u8,
    input_len: usize,
    public_json: *mut PopBuf,
    err: *mut PopBuf,
) -> i32 {
    guard(err, || {
        let p = handle(p)?;
        let w = p.witness(text(input_json, input_len, "input_json")?)?;
        let pubs = p.check(&w)?;
        put(public_json, public_to_json(&pubs).into_bytes());
        Ok(())
    })
}

/// Witness -> constraint check -> proof (bincode R1CSSNARK, ~1.6 MB). Refuses unsatisfied witnesses.
#[no_mangle]
pub unsafe extern "C" fn pop_prover_prove(
    p: *const Prover,
    input_json: *const u8,
    input_len: usize,
    proof: *mut PopBuf,
    err: *mut PopBuf,
) -> i32 {
    guard(err, || {
        let p = handle(p)?;
        let (b, _, _) = p.prove(text(input_json, input_len, "input_json")?)?;
        put(proof, b);
        Ok(())
    })
}

/// One shot: open + prove + close.
#[no_mangle]
pub unsafe extern "C" fn pop_prove(
    pk_path: *const c_char,
    input_json: *const u8,
    input_len: usize,
    proof: *mut PopBuf,
    err: *mut PopBuf,
) -> i32 {
    guard(err, || {
        let p = Prover::load(Path::new(cstr(pk_path, "pk_path")?))?;
        let (b, _, _) = p.prove(text(input_json, input_len, "input_json")?)?;
        put(proof, b);
        Ok(())
    })
}

/// SNARK verify against a vk file. If expected_json is non-null the public vector must equal it.
/// public_json (optional) gets the proof's public values.
#[no_mangle]
pub unsafe extern "C" fn pop_verify(
    vk_path: *const c_char,
    proof: *const u8,
    proof_len: usize,
    expected_json: *const u8,
    expected_len: usize,
    public_json: *mut PopBuf,
    err: *mut PopBuf,
) -> i32 {
    guard(err, || {
        let v = Verifier::load(Path::new(cstr(vk_path, "vk_path")?))?;
        let exp = if expected_json.is_null() { None } else { Some(public_from_json(text(expected_json, expected_len, "expected_json")?)?) };
        let got = v.verify(bytes(proof, proof_len, "proof")?, exp.as_deref())?;
        put(public_json, public_to_json(&got).into_bytes());
        Ok(())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn errors_cross_the_boundary() {
        unsafe {
            let mut e = PopBuf { ptr: ptr::null_mut(), len: 0 };
            let mut h: *mut Prover = ptr::null_mut();
            let rc = pop_prover_open(c"/nonexistent.pk".as_ptr(), &mut h, &mut e);
            assert_eq!(rc, Code::Io as i32);
            assert!(h.is_null());
            let msg = std::str::from_utf8(std::slice::from_raw_parts(e.ptr, e.len)).unwrap().to_string();
            assert!(msg.contains("nonexistent"), "{msg}");
            pop_buf_free(e);
            let mut e = PopBuf { ptr: ptr::null_mut(), len: 0 };
            assert_eq!(pop_prover_check(ptr::null(), b"{}".as_ptr(), 2, ptr::null_mut(), &mut e), Code::Arg as i32);
            pop_buf_free(e);
            assert_eq!(pop_prover_sample_rate(ptr::null()), 0);
            assert!(CStr::from_ptr(pop_prover_version()).to_str().unwrap().starts_with("pop-prover"));
        }
    }
}
