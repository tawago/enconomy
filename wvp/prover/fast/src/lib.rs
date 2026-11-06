//! Fast wrapper. Same prover calls as ../plain/src/lib.rs, in the same order.
//! Differences, all at the wrapper level:
//!  1. Decoded keys and the decoded Prepare state are kept in statics, instead of being decoded on each call.
//!  2. Each call records how long its stages took.
//!  4. oa_present_begin/oa_present_finish run the Prepare reblind on the pool while Show is being proved. The two share
//!     only the random shared_blinds, chosen first. Same reblind_in_memory calls with the same arguments as oa_present.
//!  3. With wasm atomics, a rayon pool runs on Web Workers. Spartan2 already uses rayon, it just has one thread without this.
//! No Spartan2 or ecdsa-spartan2 source is changed.
use ecdsa_spartan2::{
    circuit_size::CircuitSize, parse_witness, prove_circuit_in_memory, reblind_in_memory,
    PrepareCircuit, ShowCircuit,
};
use ecdsa_spartan2::{Scalar, E};
use ff::Field;
use spartan2::{traits::snark::R1CSSNARKTrait, zk_spartan::R1CSSNARK};
use spartan2::r1cs::{R1CSWitness, SplitR1CSInstance};
use std::sync::{Arc, Condvar, Mutex};

#[link(wasm_import_module = "openac_host")]
extern "C" {
    fn host_log(ptr: *const u8, len: usize);
    fn host_now_ms() -> f64;
}

type Pk = <R1CSSNARK<E> as R1CSSNARKTrait<E>>::ProverKey;
type Vk = <R1CSSNARK<E> as R1CSSNARKTrait<E>>::VerifierKey;

// Only the JS caller's thread ever touches these. Pool threads only see borrowed data inside a prover call.
struct State {
    result: Vec<u8>,
    timings: String,
    prepare_pk: Option<Pk>,
    show_pk: Option<Pk>,
    prepare_vk: Option<Vk>,
    show_vk: Option<Vk>,
    prepare_state: Option<(SplitR1CSInstance<E>, R1CSWitness<E>)>,
    pending: Option<Pending>,
}
struct Pending { blinds: Vec<Scalar>, slot: Arc<(Mutex<Option<Result<ReblindOut, String>>>, Condvar)>, started: f64 }
struct ReblindOut { proof: Vec<u8>, instance: Vec<u8>, ms: f64 }
static mut ST: Option<State> = None;
#[allow(static_mut_refs)]
fn st() -> &'static mut State {
    unsafe {
        ST.get_or_insert_with(|| State { result: Vec::new(), timings: String::new(), prepare_pk: None, show_pk: None, prepare_vk: None, show_vk: None, prepare_state: None, pending: None })
    }
}

fn now() -> f64 { unsafe { host_now_ms() } }
struct Clock(f64, String);
impl Clock {
    fn new() -> Self { Clock(now(), String::new()) }
    fn lap(&mut self, name: &str) {
        let t = now();
        self.1.push_str(&format!("{}={:.1};", name, t - self.0));
        self.0 = t;
    }
    fn finish(self) { st().timings = self.1; }
}

fn set_result(status: u32, parts: &[&[u8]]) -> *const u8 {
    let mut out = Vec::with_capacity(8 + parts.iter().map(|p| 4 + p.len()).sum::<usize>());
    out.extend_from_slice(&status.to_le_bytes());
    out.extend_from_slice(&(parts.len() as u32).to_le_bytes());
    for p in parts {
        out.extend_from_slice(&(p.len() as u32).to_le_bytes());
        out.extend_from_slice(p);
    }
    st().result = out;
    st().result.as_ptr()
}

#[no_mangle]
pub extern "C" fn oa_result_len() -> usize { st().result.len() }
#[no_mangle]
pub extern "C" fn oa_result_free() { st().result = Vec::new() }
#[no_mangle]
pub extern "C" fn oa_timings_ptr() -> *const u8 { st().timings.as_ptr() }
#[no_mangle]
pub extern "C" fn oa_timings_len() -> usize { st().timings.len() }

#[no_mangle]
pub extern "C" fn oa_alloc(len: usize) -> *mut u8 {
    let mut v = Vec::<u8>::with_capacity(len);
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}
#[no_mangle]
pub unsafe extern "C" fn oa_free(ptr: *mut u8, len: usize) { drop(Vec::from_raw_parts(ptr, 0, len)); }

/// Aligned alloc for a worker's TLS block. Never freed: workers live as long as the tab.
#[no_mangle]
pub unsafe extern "C" fn oa_alloc_aligned(len: usize, align: usize) -> *mut u8 {
    std::alloc::alloc(std::alloc::Layout::from_size_align(len, align).unwrap())
}

#[no_mangle]
pub extern "C" fn oa_init() {
    std::panic::set_hook(Box::new(|info| {
        let s = info.to_string();
        unsafe { host_log(s.as_ptr(), s.len()) };
    }));
}

unsafe fn sl<'a>(p: *const u8, n: usize) -> &'a [u8] { std::slice::from_raw_parts(p, n) }
fn fail(msg: String) -> *const u8 { set_result(1, &[msg.as_bytes()]) }

macro_rules! tryf {
    ($e:expr, $m:literal) => {
        match $e {
            Ok(v) => v,
            Err(e) => return fail(format!(concat!($m, ": {:?}"), e)),
        }
    };
}

// ---------- thread pool (atomics builds only) ----------
#[cfg(target_feature = "atomics")]
mod pool {
    use rayon::{ThreadBuilder, ThreadPoolBuilder};
    use std::sync::{Condvar, Mutex};
    static Q: Mutex<Vec<ThreadBuilder>> = Mutex::new(Vec::new());
    static CV: Condvar = Condvar::new();

    /// Each pool Web Worker calls this and never returns.
    #[no_mangle]
    pub extern "C" fn oa_worker_loop() {
        let tb = {
            let mut g = Q.lock().unwrap();
            while g.is_empty() { g = CV.wait(g).unwrap(); }
            g.pop().unwrap()
        };
        tb.run();
    }
    /// Called once from the coordinator Worker after the pool Workers are in oa_worker_loop.
    #[no_mangle]
    pub extern "C" fn oa_pool_build(n: usize) -> i32 {
        let r = ThreadPoolBuilder::new()
            .num_threads(n)
            .spawn_handler(|tb| { Q.lock().unwrap().push(tb); CV.notify_one(); Ok(()) })
            .build_global();
        if r.is_ok() { rayon::current_num_threads() as i32 } else { -1 }
    }
}

// ---------- cached state ----------
/// Decode the four keys once. Any of them may be length 0 to skip it.
#[no_mangle]
pub unsafe extern "C" fn oa_cache_keys(
    ppk: *const u8, ppk_n: usize, spk: *const u8, spk_n: usize,
    pvk: *const u8, pvk_n: usize, svk: *const u8, svk_n: usize,
) -> *const u8 {
    let mut c = Clock::new();
    if ppk_n > 0 { st().prepare_pk = Some(tryf!(bincode::deserialize(sl(ppk, ppk_n)), "Prepare PK")); }
    c.lap("decodePreparePk");
    if spk_n > 0 { st().show_pk = Some(tryf!(bincode::deserialize(sl(spk, spk_n)), "Show PK")); }
    c.lap("decodeShowPk");
    if pvk_n > 0 { st().prepare_vk = Some(tryf!(bincode::deserialize(sl(pvk, pvk_n)), "Prepare VK")); }
    c.lap("decodePrepareVk");
    if svk_n > 0 { st().show_vk = Some(tryf!(bincode::deserialize(sl(svk, svk_n)), "Show VK")); }
    c.lap("decodeShowVk");
    c.finish();
    set_result(0, &[])
}

#[no_mangle]
pub unsafe extern "C" fn oa_cache_prepare_state(pi: *const u8, pi_n: usize, pw: *const u8, pw_n: usize) -> *const u8 {
    let i: SplitR1CSInstance<E> = tryf!(bincode::deserialize(sl(pi, pi_n)), "Prepare instance");
    let w: R1CSWitness<E> = tryf!(bincode::deserialize(sl(pw, pw_n)), "Prepare witness");
    st().prepare_state = Some((i, w));
    set_result(0, &[])
}

// ---------- prover calls ----------
#[no_mangle]
pub unsafe extern "C" fn oa_precompute_from_witness(w: *const u8, w_n: usize, s: *const u8, s_n: usize) -> *const u8 {
    let mut c = Clock::new();
    let size_str = std::str::from_utf8(sl(s, s_n)).unwrap_or("");
    let circuit_size: CircuitSize = tryf!(size_str.parse::<CircuitSize>(), "Invalid vc_size");
    let pk = st().prepare_pk.as_ref().expect("keys not cached");
    let scalars = tryf!(parse_witness(sl(w, w_n)), "Witness parsing failed");
    c.lap("parseWitness");
    let circuit = PrepareCircuit::with_witness_for_size(scalars, circuit_size);
    let (proof, instance, witness) = tryf!(prove_circuit_in_memory(circuit, pk), "Prepare proving failed");
    c.lap("prove");
    let a = tryf!(bincode::serialize(&proof), "Proof serialization failed");
    let b = tryf!(bincode::serialize(&instance), "Instance serialization failed");
    let d = tryf!(bincode::serialize(&witness), "Witness serialization failed");
    c.lap("serialize");
    c.finish();
    set_result(0, &[&a, &b, &d])
}

#[no_mangle]
pub unsafe extern "C" fn oa_precompute_show_from_witness(w: *const u8, w_n: usize) -> *const u8 {
    let mut c = Clock::new();
    let pk = st().show_pk.as_ref().expect("keys not cached");
    let scalars = tryf!(parse_witness(sl(w, w_n)), "Witness parsing failed");
    c.lap("parseWitness");
    let circuit = ShowCircuit::with_witness(scalars);
    let (proof, instance, witness) = tryf!(prove_circuit_in_memory(circuit, pk), "Show proving failed");
    c.lap("prove");
    let a = tryf!(bincode::serialize(&proof), "Proof serialization failed");
    let b = tryf!(bincode::serialize(&instance), "Instance serialization failed");
    let d = tryf!(bincode::serialize(&witness), "Witness serialization failed");
    c.lap("serialize");
    c.finish();
    set_result(0, &[&a, &b, &d])
}

/// Takes the Show state as bytes (it is new each time) and uses the cached Prepare state and keys.
#[no_mangle]
pub unsafe extern "C" fn oa_present(si: *const u8, si_n: usize, sw: *const u8, sw_n: usize) -> *const u8 {
    let mut c = Clock::new();
    let prepare_pk = st().prepare_pk.as_ref().expect("keys not cached");
    let show_pk = st().show_pk.as_ref().expect("keys not cached");
    let (pi, pw) = st().prepare_state.as_ref().expect("prepare state not cached");
    let prepare_instance = pi.clone();
    let prepare_witness = pw.clone();
    c.lap("clonePrepareState");
    let show_instance: SplitR1CSInstance<E> = tryf!(bincode::deserialize(sl(si, si_n)), "Show instance");
    let show_witness: R1CSWitness<E> = tryf!(bincode::deserialize(sl(sw, sw_n)), "Show witness");
    c.lap("decodeShowState");

    let num_shared = prepare_instance.num_shared_rows();
    let shared_blinds: Vec<Scalar> = (0..num_shared).map(|_| Scalar::random(&mut rand::thread_rng())).collect();

    let (rp, rpi, _) = tryf!(reblind_in_memory(prepare_pk, prepare_instance, prepare_witness, &shared_blinds), "Prepare reblind failed");
    c.lap("reblindPrepare");
    let (rs, rsi, _) = tryf!(reblind_in_memory(show_pk, show_instance, show_witness, &shared_blinds), "Show reblind failed");
    c.lap("reblindShow");
    let a = tryf!(bincode::serialize(&rp), "ser");
    let b = tryf!(bincode::serialize(&rpi), "ser");
    let d = tryf!(bincode::serialize(&rs), "ser");
    let e = tryf!(bincode::serialize(&rsi), "ser");
    c.lap("serialize");
    c.finish();
    set_result(0, &[&a, &b, &d, &e])
}

/// Starts the Prepare reblind on the pool and returns at once. A pending result can only be taken once, so one set of
/// blinds is never used for two presentations.
#[no_mangle]
pub unsafe extern "C" fn oa_present_begin() -> *const u8 {
    if st().pending.is_some() { return fail("a reblind is already pending".into()); }
    let pk: &'static Pk = st().prepare_pk.as_ref().expect("keys not cached");
    let (pi, pw) = st().prepare_state.as_ref().expect("prepare state not cached");
    let (instance, witness) = (pi.clone(), pw.clone());
    let num_shared = instance.num_shared_rows();
    let blinds: Vec<Scalar> = (0..num_shared).map(|_| Scalar::random(&mut rand::thread_rng())).collect();
    let slot = Arc::new((Mutex::new(None), Condvar::new()));
    let (slot2, blinds2, started) = (slot.clone(), blinds.clone(), now());
    rayon::spawn(move || {
        let r = (|| -> Result<ReblindOut, String> {
            let (p, i, _) = reblind_in_memory(pk, instance, witness, &blinds2).map_err(|e| format!("Prepare reblind failed: {:?}", e))?;
            let proof = bincode::serialize(&p).map_err(|e| format!("{:?}", e))?;
            let inst = bincode::serialize(&i).map_err(|e| format!("{:?}", e))?;
            Ok(ReblindOut { proof, instance: inst, ms: now() - started })
        })();
        *slot2.0.lock().unwrap() = Some(r);
        slot2.1.notify_all();
    });
    st().pending = Some(Pending { blinds, slot, started });
    set_result(0, &[])
}

/// 1 once the Prepare reblind is done. For the "made ahead of the visit" measurement.
#[no_mangle]
pub extern "C" fn oa_present_ready() -> i32 {
    match &st().pending { Some(p) => p.slot.0.lock().unwrap().is_some() as i32, None => 0 }
}

#[no_mangle]
pub unsafe extern "C" fn oa_present_finish(si: *const u8, si_n: usize, sw: *const u8, sw_n: usize) -> *const u8 {
    let mut c = Clock::new();
    let show_pk = st().show_pk.as_ref().expect("keys not cached");
    let Some(pending) = st().pending.take() else { return fail("no reblind pending".into()) };
    let show_instance: SplitR1CSInstance<E> = tryf!(bincode::deserialize(sl(si, si_n)), "Show instance");
    let show_witness: R1CSWitness<E> = tryf!(bincode::deserialize(sl(sw, sw_n)), "Show witness");
    c.lap("decodeShowState");
    let (rs, rsi, _) = tryf!(reblind_in_memory(show_pk, show_instance, show_witness, &pending.blinds), "Show reblind failed");
    c.lap("reblindShow");
    let out = {
        let mut g = pending.slot.0.lock().unwrap();
        while g.is_none() { g = pending.slot.1.wait(g).unwrap(); }
        g.take().unwrap()
    };
    c.lap("waitPrepareReblind");
    let out = match out { Ok(o) => o, Err(e) => return fail(e) };
    let _ = pending.started;
    c.1.push_str(&format!("reblindPrepareOnPool={:.1};", out.ms));
    let d = tryf!(bincode::serialize(&rs), "ser");
    let e = tryf!(bincode::serialize(&rsi), "ser");
    c.lap("serialize");
    c.finish();
    set_result(0, &[&out.proof, &out.instance, &d, &e])
}

/// status 0 = valid, parts = [prepare values joined by \n, show values joined by \n].
/// status 2 = invalid, parts = [error]. status 1 = deserialization error.
#[no_mangle]
pub unsafe extern "C" fn oa_verify(pp: *const u8, pp_n: usize, pi: *const u8, pi_n: usize, sp: *const u8, sp_n: usize, si: *const u8, si_n: usize) -> *const u8 {
    let mut c = Clock::new();
    let prepare_vk = st().prepare_vk.as_ref().expect("keys not cached");
    let show_vk = st().show_vk.as_ref().expect("keys not cached");
    let prepare_proof: R1CSSNARK<E> = tryf!(bincode::deserialize(sl(pp, pp_n)), "Prepare proof deserialization failed");
    let _pi: SplitR1CSInstance<E> = tryf!(bincode::deserialize(sl(pi, pi_n)), "Prepare instance deserialization failed");
    let show_proof: R1CSSNARK<E> = tryf!(bincode::deserialize(sl(sp, sp_n)), "Show proof deserialization failed");
    let _si: SplitR1CSInstance<E> = tryf!(bincode::deserialize(sl(si, si_n)), "Show instance deserialization failed");
    c.lap("decodeProofs");
    let prepare_pv = match prepare_proof.verify(prepare_vk) {
        Ok(pv) => pv,
        Err(e) => { c.finish(); return set_result(2, &[format!("Prepare proof verification failed: {:?}", e).as_bytes()]) }
    };
    c.lap("verifyPrepare");
    let show_pv = match show_proof.verify(show_vk) {
        Ok(pv) => pv,
        Err(e) => { c.finish(); return set_result(2, &[format!("Show proof verification failed: {:?}", e).as_bytes()]) }
    };
    c.lap("verifyShow");
    c.finish();
    let a = prepare_proof.comm_W_shared();
    let b = show_proof.comm_W_shared();
    if !(a.is_some() && b.is_some() && a == b) {
        return set_result(2, &[b"Shared commitment mismatch: prepare and show proofs do not share the same private data"]);
    }
    let ps: Vec<String> = prepare_pv.iter().map(|s| format!("{:?}", s)).collect();
    let ss: Vec<String> = show_pv.iter().map(|s| format!("{:?}", s)).collect();
    set_result(0, &[ps.join("\n").as_bytes(), ss.join("\n").as_bytes()])
}
