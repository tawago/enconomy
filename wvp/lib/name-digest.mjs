// The name slot's value. Same code in Node and in the browser, so issuer, site and holder can't disagree.
// The slot holds 19 decimal digits, about 63 bits, and a bigger slot means a new circuit and new keys.
// So a colliding name stays possible in theory. scrypt makes each guess cost 32 MiB and about 58 ms on an M2,
// where plain SHA-256 cost about 8 ns. Input must already be normalized.
import { scrypt } from "@noble/hashes/scrypt";

export const NAME_DIGEST_PARAMS = { N: 2 ** 15, r: 8, p: 1, dkLen: 8 };
export const NAME_DIGEST_SALT = "wvp-name-digest-v1";

const seen = new Map();
export function nameDigest(name) {
  let d = seen.get(name);
  if (d === undefined) {
    const out = scrypt(name, NAME_DIGEST_SALT, NAME_DIGEST_PARAMS);
    d = out.reduce((v, b) => (v << 8n) | BigInt(b), 0n) % 10n ** 19n;
    seen.set(name, d);
  }
  return d;
}
