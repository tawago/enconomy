// Links the circom C++ witness generators in ./cpp (scripts/sync_circuits.sh) through witnesscalc-adapter.
// Before handing over to the adapter it prepares its witnesscalc checkout in OUT_DIR:
//   - pinned witnesscalc commits (same as the spike's build),
//   - GMP: host macOS uses Homebrew GMP 6.3.0 (GMP 6.2.1 arm64 asm uses x18, reserved on Darwin ->
//     random segfaults; spike fix_gmp.sh), Android is configured with --disable-assembly (x18 is
//     reserved on Android too), iOS already builds GMP without asm.
//   - Android: NDK r28 has no libc++.so/libc++.a, but the adapter always asks for -lc++; a linker
//     script shim maps it to the static libc++ so the .so has no libc++_shared.so dependency.
use std::{
    env, fs,
    path::{Path, PathBuf},
    process::Command,
};

const CIRCUITS: [&str; 2] = ["oa2t_s48", "oa2t_s44"];
const WC_GIT: &str = "https://github.com/zkmopro/witnesscalc.git";
const WC_V21: &str = "d0e66a52b219966f4a0b64d70c0aa40791b79f97"; // secq256r1-support
const WC_V22: &str = "707dc54877ad3226042d959d7ec956ae540a9a3e"; // secq256r1-support-v2.2.0

fn run(cmd: &mut Command) {
    let st = cmd.status().unwrap_or_else(|e| panic!("spawn {cmd:?}: {e}"));
    assert!(st.success(), "{cmd:?} failed: {st}");
}

fn clone_witnesscalc(wc: &Path) {
    let url = env::var("POP_WITNESSCALC_GIT").unwrap_or_else(|_| WC_GIT.to_string());
    let _ = fs::remove_dir_all(wc);
    run(Command::new("git").args(["clone", "-q", &url]).arg(wc));
    run(Command::new("git").current_dir(wc).args(["submodule", "update", "--init", "--recursive"]));
    run(Command::new("git").current_dir(wc).args(["branch", "-f", "secq256r1-support", WC_V21]));
    run(Command::new("git").current_dir(wc).args(["branch", "-f", "secq256r1-support-v2.2.0", WC_V22]));
    run(Command::new("git").current_dir(wc).args(["checkout", "-q", "secq256r1-support"]));
    if let Ok(tb) = env::var("POP_GMP_TARBALL") {
        fs::copy(&tb, wc.join("depends/gmp-6.2.1.tar.xz")).expect("copy POP_GMP_TARBALL");
    }
}

fn homebrew_gmp(wc: &Path) {
    let pkg = wc.join("depends/gmp/package");
    if pkg.join("lib/libgmp.a").exists() {
        return;
    }
    let brew = PathBuf::from(env::var("POP_HOST_GMP").unwrap_or_else(|_| "/opt/homebrew".into()));
    fs::create_dir_all(pkg.join("lib")).unwrap();
    fs::create_dir_all(pkg.join("include")).unwrap();
    fs::copy(brew.join("lib/libgmp.a"), pkg.join("lib/libgmp.a")).expect("need Homebrew gmp (brew install gmp)");
    fs::copy(brew.join("include/gmp.h"), pkg.join("include/gmp.h")).unwrap();
}

fn android_noasm(wc: &Path) {
    let p = wc.join("build_gmp.sh");
    let s = fs::read_to_string(&p).unwrap();
    let from = "--with-pic --disable-fft &&";
    if s.contains(from) {
        fs::write(&p, s.replace(from, "--with-pic --disable-fft --disable-assembly &&")).unwrap();
        // drop anything built before the patch
        let _ = fs::remove_dir_all(wc.join("depends/gmp/package_android_arm64"));
        let _ = fs::remove_dir_all(wc.join("depends/gmp/build_android_arm64"));
    }
}

fn android_cxx_shim(out: &Path) {
    let d = out.join("ndkshim");
    fs::create_dir_all(&d).unwrap();
    fs::write(d.join("libc++.a"), "INPUT(-lc++_static -lc++abi)\n").unwrap();
    println!("cargo:rustc-link-search=native={}", d.display());
}

fn main() {
    let man = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let cpp = man.join("cpp");
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-env-changed=POP_WITNESSCALC_GIT");
    for c in CIRCUITS {
        println!("cargo::rustc-check-cfg=cfg(has_{c})");
        if cpp.join(format!("{c}.cpp")).exists() {
            println!("cargo:rustc-cfg=has_{c}");
        }
    }
    assert!(
        CIRCUITS.iter().any(|c| cpp.join(format!("{c}.cpp")).exists()),
        "no circuits in {}: run scripts/sync_circuits.sh",
        cpp.display()
    );

    let target = env::var("TARGET").unwrap();
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let wc = out.join("witnesscalc");
    if !wc.join("Makefile").exists() {
        clone_witnesscalc(&wc);
    }
    match target.as_str() {
        "aarch64-apple-darwin" => homebrew_gmp(&wc),
        t if t.contains("android") => {
            android_noasm(&wc);
            android_cxx_shim(&out);
            if env::var("ANDROID_NDK").is_err() {
                let ndk = env::var("ANDROID_NDK_HOME").expect("set ANDROID_NDK (NDK root)");
                env::set_var("ANDROID_NDK", ndk);
            }
        }
        t if t.contains("apple-ios") => {
            // GMP's configure builds host tools with plain clang, which IPHONEOS_DEPLOYMENT_TARGET would
            // retarget to iOS: build GMP first without it, then set it for witnesscalc/cc objects so
            // they match the app (17.2) instead of the SDK default.
            let (gmp_t, pkg) = if t.ends_with("-sim") { ("ios_simulator", "package_iphone_simulator_arm64") } else { ("ios", "package_ios_arm64") };
            if !wc.join("depends/gmp").join(pkg).exists() {
                run(Command::new("bash").current_dir(&wc).args(["./build_gmp.sh", gmp_t]).env_remove("IPHONEOS_DEPLOYMENT_TARGET"));
            }
            if env::var("IPHONEOS_DEPLOYMENT_TARGET").is_err() {
                env::set_var("IPHONEOS_DEPLOYMENT_TARGET", "16.0");
            }
        }
        _ => {}
    }

    witnesscalc_adapter::build_and_link(cpp.to_str().unwrap());

    // The adapter also asks for -l<dylib> on the host; drop the dylibs so the host binary links statically
    // and runs without DYLD_LIBRARY_PATH.
    if target.ends_with("apple-darwin") {
        if let Ok(rd) = fs::read_dir(wc.join("package/lib")) {
            for e in rd.flatten() {
                if e.path().extension().is_some_and(|x| x == "dylib") {
                    let _ = fs::remove_file(e.path());
                }
            }
        }
    }
}
