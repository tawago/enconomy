// Links the circom C++ witness generators found in ../build/cpp (one per compiled circuit)
// and sets cfg has_<name> for each so main.rs only references what exists.
const NAMES: [&str; 11] = ["oa2_d1_sig", "oa2_d2_sig", "oa2_d5_sig", "oa2_d1_audio", "oa2_d2_audio",
    "oa2_d5_audio", "oa2_pair", "oa2_d2_sig_w60", "oa2t_s48", "oa2t_s44", "oa2t_pair"];
fn main() {
    let dir = std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap())
        .parent().unwrap().join("build/cpp");
    for name in NAMES {
        println!("cargo::rustc-check-cfg=cfg(has_{})", name);
        if dir.join(format!("{name}.cpp")).exists() {
            println!("cargo:rustc-cfg=has_{}", name);
        }
    }
    println!("cargo:rerun-if-changed={}", dir.display());
    witnesscalc_adapter::build_and_link(dir.to_str().unwrap());
}
