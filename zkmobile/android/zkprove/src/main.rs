//! zkprove CLI (runs on Android via adb shell, or on the laptop).
//!   zkprove prove <phone.json> <witness.gz>  <bn254_g1.dat> <vk|-> <outdir>
//!   zkprove full  <phone.json> <Prover.toml> <bn254_g1.dat> <vk|-> <outdir>   (feature "witness")
use std::time::Instant;
use zkprove::*;

fn rd(p: &str) -> Vec<u8> {
    std::fs::read(p).unwrap_or_else(|e| panic!("read {p}: {e}"))
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    if a.len() < 7 {
        eprintln!("usage: zkprove prove|full <phone.json> <witness.gz|Prover.toml> <bn254_g1.dat> <vk|-> <outdir>");
        std::process::exit(2);
    }
    let t0 = Instant::now();
    let art = rd(&a[2]);
    let acir = bytecode_from_artifact(&art).expect("bytecode");
    let vk = if a[5] == "-" { vec![] } else { rd(&a[5]) };
    let g1 = rd(&a[4]);
    let t_load = t0.elapsed();
    eprintln!("load: {:?} acir {} B, g1 {} B, hwm {} kB", t_load, acir.len(), g1.len(), vm_hwm_kb());

    let t = Instant::now();
    let witness = match a[1].as_str() {
        "prove" => gunzip(&rd(&a[3])).expect("witness"),
        #[cfg(feature = "witness")]
        "full" => {
            let toml = String::from_utf8(rd(&a[3])).expect("utf8");
            witness::solve(&art, &toml).expect("witness solve")
        }
        m => panic!("unknown mode {m}"),
    };
    drop(art);
    let t_wit = t.elapsed();
    eprintln!("witness: {:?} ({} B), hwm {} kB", t_wit, witness.len(), vm_hwm_kb());

    let t = Instant::now();
    init_srs(&g1, 1 << 20).expect("srs");
    drop(g1);
    let t_srs = t.elapsed();
    eprintln!("srs: {:?}, hwm {} kB", t_srs, vm_hwm_kb());

    let t = Instant::now();
    let p = prove_raw(acir, &witness, vk).expect("prove");
    let t_prove = t.elapsed();
    std::fs::create_dir_all(&a[6]).unwrap();
    std::fs::write(format!("{}/proof", a[6]), &p.proof).unwrap();
    std::fs::write(format!("{}/public_inputs", a[6]), &p.public_inputs).unwrap();
    println!(
        "RESULT mode={} load_ms={} witness_ms={} srs_ms={} prove_ms={} total_ms={} peak_rss_kb={} proof_bytes={} public_input_bytes={}",
        a[1],
        t_load.as_millis(),
        t_wit.as_millis(),
        t_srs.as_millis(),
        t_prove.as_millis(),
        t0.elapsed().as_millis(),
        vm_hwm_kb(),
        p.proof.len(),
        p.public_inputs.len()
    );
}
