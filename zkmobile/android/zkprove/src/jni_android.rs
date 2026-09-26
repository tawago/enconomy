//! JNI entry points for Kotlin (mirrors app/prover/src/jni_android.rs):
//!   package com.enconomy.pop.zk
//!   object ZkProverNative {
//!     init { System.loadLibrary("zkprove") }
//!     @JvmStatic external fun version(): String
//!     // ACVM witness from Prover.toml-style inputs + UltraHonk prove (evm target). Returns [proof, publicInputs].
//!     @JvmStatic external fun prove(circuitJsonPath: String, inputsToml: ByteArray, crsPath: String, vkPath: String?): Array<ByteArray>
//!     // Same, from a nargo-made witness (gzipped WitnessStack).
//!     @JvmStatic external fun proveWitness(circuitJsonPath: String, witnessGz: ByteArray, crsPath: String, vkPath: String?): Array<ByteArray>
//!   }
//! Failures throw RuntimeException("zkprove: <message>"). ~20-25 s and ~1.6 GB on a Pixel 6: call off the UI thread.
use crate::{bytecode_from_artifact, gunzip, init_srs, prove_raw, Res};
use jni::objects::{JByteArray, JClass, JObject, JString};
use jni::sys::{jobjectArray, jstring};
use jni::JNIEnv;
use std::panic::{catch_unwind, AssertUnwindSafe};

fn s(env: &mut JNIEnv, j: &JString) -> Res<Option<String>> {
    if j.is_null() {
        return Ok(None);
    }
    env.get_string(j).map(|x| Some(x.into())).map_err(|e| format!("jni: {e}"))
}

fn go(
    env: &mut JNIEnv,
    circuit: JString,
    input: JByteArray,
    crs: JString,
    vk: JString,
    witness: impl FnOnce(&[u8], &[u8]) -> Res<Vec<u8>>,
) -> jobjectArray {
    let r = catch_unwind(AssertUnwindSafe(|| -> Res<jobjectArray> {
        let cp = s(env, &circuit)?.ok_or("circuit path is null")?;
        let crs = s(env, &crs)?.ok_or("crs path is null")?;
        let vk = match s(env, &vk)? {
            Some(p) => std::fs::read(&p).map_err(|e| format!("{p}: {e}"))?,
            None => vec![],
        };
        let inp = env.convert_byte_array(&input).map_err(|e| format!("jni: {e}"))?;
        let art = std::fs::read(&cp).map_err(|e| format!("{cp}: {e}"))?;
        let acir = bytecode_from_artifact(&art)?;
        let w = witness(&art, &inp)?;
        drop(art);
        {
            let g1 = std::fs::read(&crs).map_err(|e| format!("{crs}: {e}"))?;
            init_srs(&g1, 1 << 20)?;
        }
        let p = prove_raw(acir, &w, vk)?;
        let je = |e: jni::errors::Error| format!("jni: {e}");
        let a = env.new_object_array(2, "[B", JObject::null()).map_err(je)?;
        let pb = env.byte_array_from_slice(&p.proof).map_err(je)?;
        let ib = env.byte_array_from_slice(&p.public_inputs).map_err(je)?;
        env.set_object_array_element(&a, 0, pb).map_err(je)?;
        env.set_object_array_element(&a, 1, ib).map_err(je)?;
        Ok(a.into_raw())
    }));
    let msg = match r {
        Ok(Ok(a)) => return a,
        Ok(Err(m)) => m,
        Err(_) => "panic in native prover".into(),
    };
    let _ = env.throw_new("java/lang/RuntimeException", format!("zkprove: {msg}"));
    std::ptr::null_mut()
}

#[no_mangle]
pub extern "system" fn Java_com_enconomy_pop_zk_ZkProverNative_version(env: JNIEnv, _: JClass) -> jstring {
    let v = unsafe { std::ffi::CStr::from_ptr(crate::ffi::zk_version()) }.to_string_lossy().into_owned();
    env.new_string(v).map(|x| x.into_raw()).unwrap_or(std::ptr::null_mut())
}

#[cfg(feature = "witness")]
#[no_mangle]
pub extern "system" fn Java_com_enconomy_pop_zk_ZkProverNative_prove(
    mut env: JNIEnv,
    _: JClass,
    circuit: JString,
    inputs_toml: JByteArray,
    crs: JString,
    vk: JString,
) -> jobjectArray {
    go(&mut env, circuit, inputs_toml, crs, vk, |art, t| {
        crate::witness::solve(art, std::str::from_utf8(t).map_err(|_| "inputs not UTF-8".to_string())?)
    })
}

#[no_mangle]
pub extern "system" fn Java_com_enconomy_pop_zk_ZkProverNative_proveWitness(
    mut env: JNIEnv,
    _: JClass,
    circuit: JString,
    witness_gz: JByteArray,
    crs: JString,
    vk: JString,
) -> jobjectArray {
    go(&mut env, circuit, witness_gz, crs, vk, |_, w| gunzip(w))
}
