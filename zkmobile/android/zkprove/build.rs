// Android: the release libbb-external.a is built with zig 0.15 (clang 20, libc++ in namespace std::__1),
// so the NDK libc++ (std::__ndk1) cannot satisfy it. Link zig's own libc++/libc++abi for
// aarch64-linux-android (built by build_zig_libcxx.sh into ZIG_CXX_DIR) statically instead.
fn main() {
    println!("cargo:rerun-if-env-changed=ZIG_CXX_DIR");
    if std::env::var("TARGET").unwrap_or_default().contains("android") {
        let d = std::env::var("ZIG_CXX_DIR").expect("set ZIG_CXX_DIR (see build_android.sh)");
        println!("cargo:rustc-link-search=native={d}");
        println!("cargo:rustc-link-lib=static=zigc++");
        println!("cargo:rustc-link-lib=static=zigc++abi");
        println!("cargo:rustc-link-lib=unwind");
        cc::Build::new().file("src/tls_align.c").compile("zktlsalign");
    }
}
