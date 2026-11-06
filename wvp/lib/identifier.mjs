// What a typed string means. Same file in the extension and the site, so they can't disagree.
// The name slot holds one digest. A credential is for one string. An address gets its own string, with a prefix no ENS name can
// have: normalize() refuses ":", so a name can never collide with someone's address slot.
import { normalize } from "viem/ens";
export const ADDR_PREFIX = "wvp-addr:";

// Returns { kind, claim, slot } or null. claim is what the site may show. slot is what goes through nameDigest.
export function parseIdentifier(typed) {
  if (typeof typed !== "string") return null;
  const s = typed.trim();
  if (/^0x[0-9a-fA-F]{40}$/.test(s)) { const claim = s.toLowerCase(); return { kind: "address", claim, slot: ADDR_PREFIX + claim }; }
  if (/^0x[0-9a-fA-F]*$/.test(s)) return null; // Looks like an address, wrong length.
  let n;
  try { n = normalize(s); } catch { return null; }
  if (!n.includes(".")) return null;
  return { kind: "name", claim: n, slot: n };
}
export const addressSlot = (address) => ADDR_PREFIX + address.toLowerCase();

