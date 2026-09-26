//! oa-vega: the JBL250 arrival statement (same as ../gen_circuit.py) on Spartan2/Vega
//! (zero-knowledge single-circuit prover, Hyrax PCS on the T-256 curve, scalar field = P-256 base field).
//!
//! Difference from the circom/Groth16 version: no in-circuit hashing. The window x and the claimed
//! curve (I, Q) are *precommitted* witness; the Fiat-Shamir challenges r, rho come from the
//! transcript after that commitment (Vega `num_challenges`). Everything else is the same R1CS:
//! Freivalds identity, FIR normalization, fixed floor T0, "first" rule (mode exact|cand|core).
//!
//!   oa-vega <input.json> <meta.json> <mode> [reps] [--tamper]
//!
//! input.json / meta.json are written by ../twin.py --dump (same files the circom circuit uses).

use bellpepper_core::{
    ConstraintSystem, LinearCombination, SynthesisError, Variable, num::AllocatedNum,
};
use ff::{Field, PrimeField};
use std::{sync::Arc, time::Instant};
use vega_prover::{
    provider::T256HyraxEngine,
    traits::{Engine, circuit::VegaCircuit, snark::R1CSSNARKTrait},
    vega_sc_zkp::VegaZkSNARK,
};

type E = T256HyraxEngine;
type F = <E as Engine>::Scalar;

const LOOK: usize = 240;
const W: usize = 88; // per-lag comparison width (bits)
const WA: usize = 96; // score >= T0 at the arrival

#[derive(Clone, Copy, PartialEq, Debug)]
enum Mode {
    Core,
    Cand,
    Exact,
}

#[derive(Clone, Debug)]
struct Data {
    x: Vec<i64>,
    i: Vec<i64>,
    q: Vec<i64>,
    arr: usize,
    sel: Vec<u8>,
    rsn: Vec<[u8; 3]>,
    hr_f: Vec<Vec<u8>>,
    hr_g: Vec<Vec<u8>>,
}

#[derive(Clone, Debug)]
struct Arrival {
    mode: Mode,
    l: usize,
    k: usize,
    h: Vec<i64>,
    b: u64,
    nhr: usize,
    ci: Arc<Vec<i64>>,
    cq: Arc<Vec<i64>>,
    d: Option<Arc<Data>>,
}

fn fi(v: i64) -> F {
    if v < 0 { -F::from(v.unsigned_abs()) } else { F::from(v as u64) }
}

/// A linear combination together with its value (None while building the shape).
#[derive(Clone)]
struct Lc {
    lc: LinearCombination<F>,
    v: Option<F>,
}

impl Lc {
    fn zero() -> Self {
        Lc { lc: LinearCombination::zero(), v: Some(F::ZERO) }
    }
    fn var(n: &AllocatedNum<F>) -> Self {
        Lc { lc: LinearCombination::zero() + n.get_variable(), v: n.get_value() }
    }
    fn cnst(c: F) -> Self {
        Lc { lc: LinearCombination::zero() + (c, Variable::new_unchecked(bellpepper_core::Index::Input(0))), v: Some(c) }
    }
    fn add(&self, o: &Lc) -> Lc {
        Lc { lc: self.lc.clone() + &o.lc, v: self.v.zip(o.v).map(|(a, b)| a + b) }
    }
    fn sub(&self, o: &Lc) -> Lc {
        Lc { lc: self.lc.clone() - &o.lc, v: self.v.zip(o.v).map(|(a, b)| a - b) }
    }
    fn scale(&self, c: F) -> Lc {
        let mut lc = LinearCombination::zero();
        for (var, coeff) in self.lc.iter() {
            lc = lc + (*coeff * c, var);
        }
        Lc { lc, v: self.v.map(|a| a * c) }
    }
}

/// z = a * b + c  (one constraint)
fn mul_add<CS: ConstraintSystem<F>>(cs: &mut CS, a: &Lc, b: &Lc, c: &Lc) -> Result<Lc, SynthesisError> {
    let val = match (a.v, b.v, c.v) {
        (Some(a), Some(b), Some(c)) => Some(a * b + c),
        _ => None,
    };
    let z = AllocatedNum::alloc(cs.namespace(|| ""), || val.ok_or(SynthesisError::AssignmentMissing))?;
    let zl = Lc::var(&z);
    cs.enforce(|| "", |_| a.lc.clone(), |_| b.lc.clone(), |_| zl.lc.clone() - &c.lc);
    Ok(zl)
}

fn mul<CS: ConstraintSystem<F>>(cs: &mut CS, a: &Lc, b: &Lc) -> Result<Lc, SynthesisError> {
    mul_add(cs, a, b, &Lc::zero())
}

/// a * b == c
fn enforce_eq_prod<CS: ConstraintSystem<F>>(cs: &mut CS, a: &Lc, b: &Lc, c: &Lc) {
    cs.enforce(|| "", |_| a.lc.clone(), |_| b.lc.clone(), |_| c.lc.clone());
}

fn one() -> Lc {
    Lc::cnst(F::ONE)
}

/// v in [0, 2^w): w boolean constraints + 1 packing constraint.
fn range<CS: ConstraintSystem<F>>(cs: &mut CS, v: &Lc, w: usize) -> Result<(), SynthesisError> {
    let bytes = v.v.map(|x| x.to_repr());
    let mut acc = LinearCombination::zero();
    let mut pow = F::ONE;
    for i in 0..w {
        let bit = bytes.as_ref().map(|r| (r.as_ref()[i / 8] >> (i % 8)) & 1 == 1);
        let b = AllocatedNum::alloc(cs.namespace(|| ""), || {
            bit.map(|t| if t { F::ONE } else { F::ZERO }).ok_or(SynthesisError::AssignmentMissing)
        })?;
        let bl = Lc::var(&b);
        enforce_eq_prod(cs, &bl, &bl, &bl); // b^2 = b
        acc = acc + (pow, b.get_variable());
        pow = pow.double();
    }
    cs.enforce(|| "", |_| acc, |_| one().lc, |_| v.lc.clone());
    Ok(())
}

fn alloc_bool<CS: ConstraintSystem<F>>(cs: &mut CS, v: Option<u8>) -> Result<Lc, SynthesisError> {
    let b = AllocatedNum::alloc(cs.namespace(|| ""), || v.map(|t| F::from(t as u64)).ok_or(SynthesisError::AssignmentMissing))?;
    let bl = Lc::var(&b);
    enforce_eq_prod(cs, &bl, &bl, &bl);
    Ok(bl)
}

impl VegaCircuit<E> for Arrival {
    fn public_values(&self) -> Result<Vec<F>, SynthesisError> {
        let mut p: Vec<F> = self.ci.iter().chain(self.cq.iter()).map(|&v| fi(v)).collect();
        if self.mode != Mode::Core {
            p.push(F::from(self.d.as_ref().map(|d| d.arr as u64).unwrap_or(0)));
        }
        Ok(p)
    }

    fn shared<CS: ConstraintSystem<F>>(&self, _: &mut CS) -> Result<Vec<AllocatedNum<F>>, SynthesisError> {
        Ok(vec![])
    }

    /// x (window), I, Q: committed before the challenges exist.
    fn precommitted<CS: ConstraintSystem<F>>(
        &self,
        cs: &mut CS,
        _: &[AllocatedNum<F>],
    ) -> Result<Vec<AllocatedNum<F>>, SynthesisError> {
        let (l, k, m) = (self.l, self.k, self.h.len());
        let nx = k + l - 1 + m - 1;
        let mut out = Vec::with_capacity(nx + 2 * k);
        for j in 0..nx {
            let v = self.d.as_ref().map(|d| fi(d.x[j]));
            out.push(AllocatedNum::alloc(cs.namespace(|| ""), || v.ok_or(SynthesisError::AssignmentMissing))?);
        }
        for j in 0..2 * k {
            let v = self.d.as_ref().map(|d| fi(if j < k { d.i[j] } else { d.q[j - k] }));
            out.push(AllocatedNum::alloc(cs.namespace(|| ""), || v.ok_or(SynthesisError::AssignmentMissing))?);
        }
        Ok(out)
    }

    fn num_challenges(&self) -> usize {
        2
    }

    fn synthesize<CS: ConstraintSystem<F>>(
        &self,
        cs: &mut CS,
        _: &[AllocatedNum<F>],
        pre: &[AllocatedNum<F>],
        challenges: Option<&[F]>,
    ) -> Result<(), SynthesisError> {
        let (l, k, m) = (self.l, self.k, self.h.len());
        let hm = (m - 1) / 2;
        let n = k + l - 1;
        let nx = n + m - 1;
        let d = self.d.as_ref();
        // public IO: template, arr, then the challenges
        let mut ci = Vec::with_capacity(l);
        let mut cq = Vec::with_capacity(l);
        for j in 0..l {
            let v = fi(self.ci[j]);
            ci.push(Lc::var(&AllocatedNum::alloc_input(cs.namespace(|| ""), || Ok(v))?));
        }
        for j in 0..l {
            let v = fi(self.cq[j]);
            cq.push(Lc::var(&AllocatedNum::alloc_input(cs.namespace(|| ""), || Ok(v))?));
        }
        let arr_in = if self.mode != Mode::Core {
            let v = F::from(d.map(|d| d.arr as u64).unwrap_or(0));
            Some(Lc::var(&AllocatedNum::alloc_input(cs.namespace(|| ""), || Ok(v))?))
        } else {
            None
        };
        let r = Lc::var(&AllocatedNum::alloc_input(cs.namespace(|| ""), || {
            Ok(challenges.map(|c| c[0]).unwrap_or(F::ZERO))
        })?);
        let rho = Lc::var(&AllocatedNum::alloc_input(cs.namespace(|| ""), || {
            Ok(challenges.map(|c| c[1]).unwrap_or(F::ZERO))
        })?);

        let x: Vec<Lc> = pre[..nx].iter().map(Lc::var).collect();
        let iv: Vec<Lc> = pre[nx..nx + k].iter().map(Lc::var).collect();
        let qv: Vec<Lc> = pre[nx + k..nx + 2 * k].iter().map(Lc::var).collect();

        // ---- Freivalds
        let mut pw = Vec::with_capacity(n);
        pw.push(one());
        pw.push(r.clone());
        for i in 2..n {
            let p = mul(cs, &pw[i - 1], &r)?;
            pw.push(p);
        }
        let mut s = Vec::with_capacity(n + 1);
        s.push(Lc::zero());
        for mm in 1..=n {
            let v = mul_add(cs, &pw[mm - 1], &x[hm + mm - 1], &s[mm - 1])?;
            s.push(v);
        }
        let mut acc = Lc::zero();
        for j in 0..l {
            let v = mul(cs, &rho, &cq[j])?;
            let u = mul(cs, &ci[j].add(&v), &pw[l - 1 - j])?;
            acc = mul_add(cs, &u, &s[j + k].sub(&s[j]), &acc)?;
        }
        let mut li = Lc::zero();
        let mut lq = Lc::zero();
        for j in 0..k {
            li = mul_add(cs, &pw[j], &iv[j], &li)?;
            lq = mul_add(cs, &pw[j], &qv[j], &lq)?;
        }
        let lhs = mul_add(cs, &rho, &lq, &li)?;
        enforce_eq_prod(cs, &pw[l - 1], &lhs, &acc);
        drop(pw);
        drop(s);

        if self.mode == Mode::Core {
            return Ok(());
        }

        // ---- normalization
        let mut ey = Vec::with_capacity(n + 1);
        ey.push(Lc::zero());
        for mm in 0..n {
            let mut y = Lc::zero();
            for (t, &hv) in self.h.iter().enumerate() {
                if hv != 0 {
                    y = y.add(&x[mm + t].scale(fi(hv)));
                }
            }
            let v = mul_add(cs, &y, &y, &ey[mm])?;
            ey.push(v);
        }
        let mut cn2 = Lc::zero();
        for j in 0..l {
            cn2 = mul_add(cs, &ci[j], &ci[j], &cn2)?;
        }
        let mut c = Vec::with_capacity(k);
        let mut env2 = Vec::with_capacity(k);
        for j in 0..k {
            c.push(mul(cs, &ey[j + l].sub(&ey[j]), &cn2)?);
            let i2 = mul(cs, &iv[j], &iv[j])?;
            env2.push(mul_add(cs, &qv[j], &qv[j], &i2)?);
        }
        drop(ey);

        // ---- selector sel[k] = [k <= arr]
        let mut sel = Vec::with_capacity(k + 1);
        for j in 0..=k {
            sel.push(alloc_bool(cs, d.map(|d| d.sel[j]))?);
        }
        let mut ssum = Lc::zero();
        for j in 0..=k {
            ssum = ssum.add(&sel[j]);
        }
        let arr_in = arr_in.unwrap();
        enforce_eq_prod(cs, &ssum, &one(), &arr_in.add(&one()));
        enforce_eq_prod(cs, &sel[0], &one(), &one());
        enforce_eq_prod(cs, &sel[1], &one(), &one());
        enforce_eq_prod(cs, &sel[k - 1], &one(), &Lc::zero());
        enforce_eq_prod(cs, &sel[k], &one(), &Lc::zero());
        for j in 0..k {
            enforce_eq_prod(cs, &sel[j + 1], &one().sub(&sel[j]), &Lc::zero());
        }
        let e: Vec<Lc> = (0..k).map(|j| sel[j].sub(&sel[j + 1])).collect();
        let (mut ae, mut am, mut ap, mut ac) = (Lc::zero(), Lc::zero(), Lc::zero(), Lc::zero());
        for j in 0..k {
            ae = mul_add(cs, &e[j], &env2[j], &ae)?;
            am = mul_add(cs, &e[j], &if j >= 1 { env2[j - 1].clone() } else { Lc::zero() }, &am)?;
            ap = mul_add(cs, &e[j], &if j + 1 < k { env2[j + 1].clone() } else { Lc::zero() }, &ap)?;
            ac = mul_add(cs, &e[j], &c[j], &ac)?;
        }
        range(cs, &ae.scale(F::from(self.b)).sub(&ac), WA)?;
        range(cs, &ae.sub(&am), W)?;
        range(cs, &ae.sub(&ap).sub(&one()), W)?;

        let la = |j: usize| -> Lc {
            let a = one().sub(&sel[j + 1]);
            if j >= LOOK { a.sub(&one().sub(&sel[j - LOOK])) } else { a }
        };
        let four_ae = ae.scale(F::from(4u64));

        if self.mode == Mode::Cand {
            for j in 0..k {
                let p4 = mul(cs, &la(j), &four_ae.sub(&env2[j]))?;
                range(cs, &p4, W)?;
            }
            return Ok(());
        }

        // ---- exact: every lag before arr carries a reason (a derived: sel[k+1] - b - c - hr)
        let mut hf = vec![vec![]; self.nhr];
        let mut hg = vec![vec![]; self.nhr];
        for w in 0..self.nhr {
            for j in 0..k {
                hf[w].push(alloc_bool(cs, d.map(|d| d.hr_f[w][j]))?);
                hg[w].push(alloc_bool(cs, d.map(|d| d.hr_g[w][j]))?);
            }
        }
        let b = F::from(self.b);
        for j in 0..k {
            let rb = alloc_bool(cs, d.map(|d| d.rsn[j][1]))?;
            let rc = alloc_bool(cs, d.map(|d| d.rsn[j][2]))?;
            let mut hs = Lc::zero();
            for w in 0..self.nhr {
                hs = hs.add(&hf[w][j]);
            }
            let ra = sel[j + 1].sub(&rb).sub(&rc).sub(&hs);
            enforce_eq_prod(cs, &ra, &ra, &ra);
            let p1 = mul(cs, &ra, &c[j].sub(&env2[j].scale(b)).sub(&one()))?;
            let db = if j + 1 < k { env2[j + 1].sub(&env2[j]) } else { Lc::cnst(-F::ONE) };
            let p2 = mul(cs, &rb, &db)?;
            let dc = if j >= 1 { env2[j - 1].sub(&env2[j]).sub(&one()) } else { Lc::zero() };
            let p3 = mul(cs, &rc, &dc)?;
            let p4 = mul(cs, &la(j), &four_ae.sub(&env2[j]))?;
            range(cs, &p1.add(&p2).add(&p3).add(&p4), W)?;
        }
        for w in 0..self.nhr {
            let (mut fj, mut gm) = (Lc::zero(), Lc::zero());
            let (mut fs, mut gs, mut fidx, mut gidx) = (Lc::zero(), Lc::zero(), Lc::zero(), Lc::zero());
            for j in 0..k {
                fj = mul_add(cs, &hf[w][j], &env2[j], &fj)?;
                gm = mul_add(cs, &hg[w][j], &env2[j], &gm)?;
                fs = fs.add(&hf[w][j]);
                gs = gs.add(&hg[w][j]);
                fidx = fidx.add(&hf[w][j].scale(F::from(j as u64)));
                gidx = gidx.add(&hg[w][j].scale(F::from(j as u64)));
            }
            enforce_eq_prod(cs, &fs, &fs, &fs);
            enforce_eq_prod(cs, &gs, &one(), &fs);
            range(cs, &gidx.sub(&fidx), 9)?;
            range(cs, &fs.scale(F::from(LOOK as u64)).sub(&gidx.sub(&fidx)), 9)?;
            let t = mul(cs, &fs, &gm.sub(&fj.scale(F::from(4u64))).sub(&one()))?;
            range(cs, &t, W)?;
        }
        Ok(())
    }
}

fn arr_i64(v: &serde_json::Value) -> Vec<i64> {
    v.as_array().unwrap().iter().map(|x| x.as_i64().unwrap()).collect()
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    if a.len() < 4 {
        eprintln!("usage: oa-vega <input.json> <meta.json> <core|cand|exact> [reps] [--tamper]");
        std::process::exit(2);
    }
    let inp: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&a[1]).unwrap()).unwrap();
    let meta: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&a[2]).unwrap()).unwrap();
    let mode = match a[3].as_str() {
        "core" => Mode::Core,
        "cand" => Mode::Cand,
        _ => Mode::Exact,
    };
    let reps: usize = a.get(4).and_then(|s| s.parse().ok()).unwrap_or(1);
    let tamper = a.iter().any(|s| s == "--tamper");
    let h = arr_i64(&meta["fir"]);
    let b = meta["B"].as_u64().unwrap();
    let ci = Arc::new(arr_i64(&inp["cI"]));
    let cq = Arc::new(arr_i64(&inp["cQ"]));
    let mut data = Data {
        x: arr_i64(&inp["x"]),
        i: arr_i64(&inp["I"]),
        q: arr_i64(&inp["Q"]),
        arr: inp.get("arr").and_then(|v| v.as_u64()).unwrap_or(0) as usize,
        sel: inp.get("sel").map(|v| arr_i64(v).iter().map(|&t| t as u8).collect()).unwrap_or_default(),
        rsn: inp
            .get("rsn")
            .map(|v| v.as_array().unwrap().iter().map(|r| {
                let r = arr_i64(r);
                [r[0] as u8, r[1] as u8, r[2] as u8]
            }).collect())
            .unwrap_or_default(),
        hr_f: inp.get("hr_f").map(|v| v.as_array().unwrap().iter().map(|r| arr_i64(r).iter().map(|&t| t as u8).collect()).collect()).unwrap_or_default(),
        hr_g: inp.get("hr_g").map(|v| v.as_array().unwrap().iter().map(|r| arr_i64(r).iter().map(|&t| t as u8).collect()).collect()).unwrap_or_default(),
    };
    let k = data.i.len();
    let l = ci.len();
    let nhr = data.hr_f.len();
    if tamper {
        data.i[k / 3] += 1; // one altered score
    }
    assert_eq!(F::from(5u64).to_repr().as_ref()[0], 5, "repr must be little-endian");
    let shape = Arrival { mode, l, k, h: h.clone(), b, nhr, ci: ci.clone(), cq: cq.clone(), d: None };
    let full = Arrival { d: Some(Arc::new(data)), ..shape.clone() };

    let t = Instant::now();
    let (pk, vk) = VegaZkSNARK::<E>::setup(shape).expect("setup");
    let setup_ms = t.elapsed().as_millis();
    let sizes = pk.sizes();
    println!("RESULT setup mode={:?} L={l} K={k} setup_ms={setup_ms} sizes={:?}", mode, sizes);
    for rep in 0..reps {
        let t = Instant::now();
        let prep = VegaZkSNARK::<E>::prep_prove(&pk, full.clone(), false).expect("prep_prove");
        let prep_ms = t.elapsed().as_millis();
        let t = Instant::now();
        let res = VegaZkSNARK::<E>::prove(&pk, full.clone(), prep, false);
        let prove_ms = t.elapsed().as_millis();
        match res {
            Err(e) => println!("RESULT prove rep={rep} REJECT {e:?} prep_ms={prep_ms} prove_ms={prove_ms}"),
            Ok((snark, _)) => {
                let bytes = bincode::serialize(&snark).unwrap();
                let t = Instant::now();
                let v = snark.verify(&vk);
                let verify_ms = t.elapsed().as_millis();
                let ok = match &v {
                    Ok(pubs) => {
                        let exp = full.public_values().unwrap();
                        pubs.len() >= exp.len() && pubs[..exp.len()] == exp[..]
                    }
                    Err(_) => false,
                };
                println!(
                    "RESULT prove rep={rep} tamper={tamper} prep_ms={prep_ms} prove_ms={prove_ms} verify_ms={verify_ms} verify={} proof_bytes={}",
                    if ok { "ACCEPT" } else { "REJECT" },
                    bytes.len()
                );
                if let Err(e) = v {
                    println!("  verify error: {e:?}");
                }
            }
        }
    }
}
