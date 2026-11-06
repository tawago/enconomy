use std::time::Duration;
#[link(wasm_import_module = "openac_host")]
extern "C" { fn host_now_ms() -> f64; }
#[derive(Copy, Clone, Debug, PartialEq, PartialOrd)]
pub struct Instant(f64);
impl Instant {
    pub fn now() -> Self { Instant(unsafe { host_now_ms() }) }
    pub fn elapsed(&self) -> Duration { Self::now().duration_since(*self) }
    pub fn duration_since(&self, e: Instant) -> Duration { Duration::from_secs_f64(((self.0 - e.0) / 1000.0).max(0.0)) }
}
impl std::ops::Sub for Instant { type Output = Duration; fn sub(self, o: Instant) -> Duration { self.duration_since(o) } }
