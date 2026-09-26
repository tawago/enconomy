//! Host CLI around the library (Mac tests / server-side debugging).
//!   popprover check  <pk> <input.json>                  witness + constraint check, prints halfCommit
//!   popprover prove  <pk> <input.json> <out.proof>      check + prove
//!   popprover verify <vk> <proof> [expected.json]       SNARK verify (+ exact public vector match)
//!   popprover e2e    <pk> <vk> <input.json> <expected.json> <out.proof>   prove, drop pk, verify
use pop_prover::{public_from_json, scalar_to_dec, Prover, Verifier};
use std::{fs, path::Path, process::exit, time::Instant};

fn die(stage: &str, e: impl std::fmt::Display) -> ! {
    println!("RESULT {stage} REJECT {e}");
    exit(1)
}

fn read(p: &str) -> String {
    fs::read_to_string(p).unwrap_or_else(|e| die("read", format!("{p}: {e}")))
}

fn prove(pk: &str, input: &str, out: &str) {
    let p = Prover::load(Path::new(pk)).unwrap_or_else(|e| die("load", e));
    let (b, pubs, t) = p.prove(&read(input)).unwrap_or_else(|e| die("prove", e));
    fs::write(out, &b).unwrap();
    println!(
        "RESULT prove {} ACCEPT pk_load_ms={} witness_ms={} check_ms={} prove_ms={} proof_bytes={} half_commit={}",
        p.circuit.name(),
        p.load_ms,
        t.witness_ms,
        t.check_ms,
        t.prove_ms,
        b.len(),
        scalar_to_dec(&pubs[0])
    );
}

fn verify(vk: &str, proof: &str, expected: Option<&str>) {
    let t = Instant::now();
    let v = Verifier::load(Path::new(vk)).unwrap_or_else(|e| die("verify", e));
    let load_ms = t.elapsed().as_millis();
    let exp = expected.map(|p| public_from_json(&read(p)).unwrap_or_else(|e| die("verify", e)));
    let t = Instant::now();
    let got = v.verify(&fs::read(proof).unwrap(), exp.as_deref()).unwrap_or_else(|e| die("verify", e));
    println!(
        "RESULT verify ACCEPT vk_load_ms={load_ms} verify_ms={} n_public={} matched_expected={}",
        t.elapsed().as_millis(),
        got.len(),
        exp.is_some()
    );
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let arg = |i: usize| a.get(i).map(String::as_str).unwrap_or_else(|| die("usage", "see src/bin/popprover.rs"));
    match arg(1) {
        "check" => {
            let p = Prover::load(Path::new(arg(2))).unwrap_or_else(|e| die("load", e));
            let t = Instant::now();
            let w = p.witness(&read(arg(3))).unwrap_or_else(|e| die("check", e));
            let wms = t.elapsed().as_millis();
            let t = Instant::now();
            let pubs = p.check(&w).unwrap_or_else(|e| die("check", e));
            println!(
                "RESULT check {} ACCEPT pk_load_ms={} witness_ms={wms} check_ms={} n_witness={} n_public={} half_commit={}",
                p.circuit.name(),
                p.load_ms,
                t.elapsed().as_millis(),
                w.len(),
                pubs.len(),
                scalar_to_dec(&pubs[0])
            );
        }
        "corrupt" => {
            // popprover corrupt <pk> <input.json> <index>: bump one witness value, check must refuse it.
            let p = Prover::load(Path::new(arg(2))).unwrap_or_else(|e| die("load", e));
            let mut w = p.witness(&read(arg(3))).unwrap_or_else(|e| die("corrupt", e));
            let i: usize = arg(4).parse().unwrap_or_else(|e| die("usage", e));
            w[i] += pop_prover::Scalar::from(1u64);
            match p.check(&w) {
                Ok(_) => die("corrupt", format!("w[{i}]+1 still satisfies the R1CS")),
                Err(e) => println!("RESULT corrupt ACCEPT w[{i}]+1 refused: {e}"),
            }
        }
        "prove" => prove(arg(2), arg(3), arg(4)),
        "verify" => verify(arg(2), arg(3), a.get(4).map(String::as_str)),
        "e2e" => {
            prove(arg(2), arg(4), arg(6));
            verify(arg(3), arg(6), Some(arg(5)));
        }
        c => die("usage", format!("unknown command {c}")),
    }
}
