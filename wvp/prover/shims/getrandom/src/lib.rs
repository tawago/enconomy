use core::{fmt, num::NonZeroU32};
#[derive(Copy, Clone, Eq, PartialEq, Debug)]
pub struct Error(NonZeroU32);
impl Error {
    pub const INTERNAL_START: u32 = 1 << 31;
    pub const CUSTOM_START: u32 = (1 << 31) + (1 << 30);
    pub fn raw_os_error(self) -> Option<i32> { None }
    pub const fn code(self) -> NonZeroU32 { self.0 }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { write!(f, "getrandom error {}", self.0) }
}
impl std::error::Error for Error {}
impl From<NonZeroU32> for Error { fn from(c: NonZeroU32) -> Self { Error(c) } }
#[link(wasm_import_module = "openac_host")]
extern "C" { fn host_random(ptr: *mut u8, len: usize); }
pub fn getrandom(dest: &mut [u8]) -> Result<(), Error> {
    if !dest.is_empty() { unsafe { host_random(dest.as_mut_ptr(), dest.len()) } }
    Ok(())
}
