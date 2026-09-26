//! JNI entry points for Kotlin:
//!   package com.enconomy.pop.zk
//!   object PopProverNative {
//!     init { System.loadLibrary("pop_prover") }
//!     @JvmStatic external fun open(pkPath: String): Long
//!     @JvmStatic external fun close(handle: Long)
//!     @JvmStatic external fun sampleRate(handle: Long): Int
//!     @JvmStatic external fun check(handle: Long, inputJson: ByteArray): String   // {"public": [...]}
//!     @JvmStatic external fun prove(handle: Long, inputJson: ByteArray): ByteArray // proof bytes
//!   }
//! Failures throw RuntimeException("pop-prover <Code>: <message>"). Call from a background thread.

use crate::{public_to_json, Code, Error, Prover, Res};
use jni::{
    objects::{JByteArray, JClass, JString},
    sys::{jbyteArray, jint, jlong, jstring},
    JNIEnv,
};
use std::{
    panic::{catch_unwind, AssertUnwindSafe},
    path::Path,
    ptr,
};

fn run<T>(env: &mut JNIEnv, dflt: T, f: impl FnOnce(&mut JNIEnv) -> Res<T>) -> T {
    let r = catch_unwind(AssertUnwindSafe(|| f(env)));
    let e = match r {
        Ok(Ok(v)) => return v,
        Ok(Err(e)) => e,
        Err(_) => Error { code: Code::Panic, msg: "panic in native prover".into() },
    };
    let _ = env.throw_new("java/lang/RuntimeException", format!("pop-prover {:?}: {}", e.code, e.msg));
    dflt
}

fn jerr(e: jni::errors::Error) -> Error {
    Error { code: Code::Arg, msg: format!("jni: {e}") }
}

fn prover<'a>(h: jlong) -> Res<&'a Prover> {
    unsafe { (h as *const Prover).as_ref() }.ok_or(Error { code: Code::Arg, msg: "prover handle is 0".into() })
}

fn input(env: &mut JNIEnv, a: &JByteArray) -> Res<String> {
    let b = env.convert_byte_array(a).map_err(jerr)?;
    String::from_utf8(b).map_err(|_| Error { code: Code::Arg, msg: "input is not UTF-8".into() })
}

#[no_mangle]
pub extern "system" fn Java_com_enconomy_pop_zk_PopProverNative_open(mut env: JNIEnv, _: JClass, pk: JString) -> jlong {
    run(&mut env, 0, |env| {
        let path: String = env.get_string(&pk).map_err(jerr)?.into();
        Ok(Box::into_raw(Box::new(Prover::load(Path::new(&path))?)) as jlong)
    })
}

#[no_mangle]
pub extern "system" fn Java_com_enconomy_pop_zk_PopProverNative_close(_: JNIEnv, _: JClass, h: jlong) {
    if h != 0 {
        unsafe { drop(Box::from_raw(h as *mut Prover)) };
    }
}

#[no_mangle]
pub extern "system" fn Java_com_enconomy_pop_zk_PopProverNative_sampleRate(mut env: JNIEnv, _: JClass, h: jlong) -> jint {
    run(&mut env, 0, |_| Ok(prover(h)?.circuit.sample_rate() as jint))
}

#[no_mangle]
pub extern "system" fn Java_com_enconomy_pop_zk_PopProverNative_check(
    mut env: JNIEnv,
    _: JClass,
    h: jlong,
    json: JByteArray,
) -> jstring {
    run(&mut env, ptr::null_mut(), |env| {
        let p = prover(h)?;
        let w = p.witness(&input(env, &json)?)?;
        let pubs = p.check(&w)?;
        Ok(env.new_string(public_to_json(&pubs)).map_err(jerr)?.into_raw())
    })
}

#[no_mangle]
pub extern "system" fn Java_com_enconomy_pop_zk_PopProverNative_prove(
    mut env: JNIEnv,
    _: JClass,
    h: jlong,
    json: JByteArray,
) -> jbyteArray {
    run(&mut env, ptr::null_mut(), |env| {
        let p = prover(h)?;
        let (b, _, _) = p.prove(&input(env, &json)?)?;
        Ok(env.byte_array_from_slice(&b).map_err(jerr)?.into_raw())
    })
}
