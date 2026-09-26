/* Loads libzkprove.so through dlopen (as System.loadLibrary would) and calls zk_prove on the device.
   usage: so_smoke <libzkprove.so> <phone.json> <Prover.toml> <bn254_g1.dat> <vk> <outdir> */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include "zkprove/include/zkprove.h"
static uint8_t *slurp(const char *p, size_t *n) {
  FILE *f = fopen(p, "rb"); if (!f) { perror(p); exit(2); }
  fseek(f, 0, SEEK_END); *n = ftell(f); rewind(f);
  uint8_t *b = malloc(*n); fread(b, 1, *n, f); fclose(f); return b;
}
static void dump(const char *d, const char *name, ZkBuf b) {
  char p[512]; snprintf(p, sizeof p, "%s/%s", d, name); FILE *f = fopen(p, "wb"); fwrite(b.ptr, 1, b.len, f); fclose(f);
}
int main(int c, char **v) {
  if (c < 7) return 2;
  void *h = dlopen(v[1], RTLD_NOW); if (!h) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
  const char *(*ver)(void) = dlsym(h, "zk_version");
  int (*prove)(const char *, const uint8_t *, size_t, const char *, const char *, ZkBuf *, ZkBuf *, ZkBuf *) = dlsym(h, "zk_prove");
  void (*fr)(ZkBuf) = dlsym(h, "zk_buf_free");
  printf("%s\n", ver());
  size_t n; uint8_t *t = slurp(v[3], &n);
  ZkBuf pf = {0}, pi = {0}, er = {0};
  int rc = prove(v[2], t, n, v[4], v[5], &pf, &pi, &er);
  if (rc) { fprintf(stderr, "rc=%d %.*s\n", rc, (int)er.len, er.ptr); return rc; }
  dump(v[6], "proof", pf); dump(v[6], "public_inputs", pi);
  printf("SO_OK proof=%zu public_inputs=%zu\n", pf.len, pi.len);
  fr(pf); fr(pi); return 0;
}
