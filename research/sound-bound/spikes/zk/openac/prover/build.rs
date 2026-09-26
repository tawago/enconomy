// Links the circom C++ witness generators found in ../build/cpp (one per compiled circuit)
// and sets cfg has_<name> for each so main.rs only references what exists.
fn main() {
    let dir = std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap())
        .parent().unwrap().join("build/cpp");
    for name in ["sb_pair_v1", "sb_pair_v2", "sb_half_v1", "sb_half_v2", "popt_pair", "popt_pair_nf"] {
        println!("cargo::rustc-check-cfg=cfg(has_{})", name);
        if dir.join(format!("{name}.cpp")).exists() {
            println!("cargo:rustc-cfg=has_{}", name);
        }
    }
    println!("cargo:rerun-if-changed={}", dir.display());
    witnesscalc_adapter::build_and_link(dir.to_str().unwrap());
}
