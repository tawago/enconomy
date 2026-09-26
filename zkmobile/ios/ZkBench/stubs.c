// libbb-external.a references libdeflate (gzip in get_bytecode / file IO) but the bbapi prove path
// gets already-decompressed bytecode and witness, so these are never called.
#include <stdlib.h>
#include <stdio.h>
static void die(const char *f) { fprintf(stderr, "stub %s called\n", f); abort(); }
void *libdeflate_alloc_compressor(int l) { (void)l; die("alloc_compressor"); return 0; }
void *libdeflate_alloc_decompressor(void) { die("alloc_decompressor"); return 0; }
void libdeflate_free_compressor(void *c) { (void)c; }
void libdeflate_free_decompressor(void *d) { (void)d; }
size_t libdeflate_gzip_compress(void *c, const void *i, size_t il, void *o, size_t ol) { die("gzip_compress"); return 0; }
size_t libdeflate_gzip_compress_bound(void *c, size_t n) { die("compress_bound"); return 0; }
int libdeflate_gzip_decompress(void *d, const void *i, size_t il, void *o, size_t ol, size_t *a) { die("gzip_decompress"); return 0; }
