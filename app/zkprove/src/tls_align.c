/* Bionic arm64 refuses executables/libs whose PT_TLS alignment is < 64. The zig-built bb archive
   contributes TLS with 16-byte alignment; one 64-aligned TLS object raises the segment alignment. */
__thread __attribute__((aligned(64))) char zk_tls_align[64];
char *zk_tls_align_ref(void) { return zk_tls_align; }
