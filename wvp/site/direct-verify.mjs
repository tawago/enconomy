// The site's check for a direct login. No issuer, no circuit. A wallet signature approves K, K signs this site and this challenge, ENS says who owns the name.
import { webcrypto as wc } from "node:crypto";
import { recoverMessageAddress, isAddressEqual } from "viem";
import { createSiweMessage, parseSiweMessage } from "viem/siwe";
import { parseIdentifier } from "../lib/identifier.mjs";
import { thumbprint, directStatement, loginBytes, NAME_URN, THUMB_URN } from "../lib/direct.mjs";
const MAX_LIFE = 7 * 86400, SKEW = 300;
const no = (reason, more = {}) => ({ accepted: false, reason, ...more });
const isHex = (s) => typeof s === "string";
const fromB64 = (s) => Buffer.from(s, "base64url");

// tok: { message, walletSig, key, loginSig, challenge, now, claim }. The caller has checked the challenge is live and unused, and `now` is near its clock.
// nameOnly: refuse a typed address. An address login reads no ENS, so it would still work after the name moves to another wallet.
export async function verifyDirect({ tok, origin, lookup, approveDomains, nowSec, nameOnly = false }) {
  const { message, walletSig, key, loginSig, challenge, now, claim } = tok;
  if (![message, walletSig, loginSig, claim].every(isHex) || key?.kty !== "EC" || key.crv !== "P-256") return no("bad_token");

  // Exactly the shape we'd write, so a parser quirk can't make the wallet's text and these fields differ.
  let m;
  try { m = parseSiweMessage(message); if (createSiweMessage(m) !== message) return no("bad_message"); } catch { return no("bad_message"); }
  if (m.version !== "1" || m.chainId !== 1 || !m.address || !m.expirationTime || !m.issuedAt) return no("bad_message");
  // The approval must have been asked for on a page this site trusts to ask. See browser/SPEC.md, rule 4.
  if (!approveDomains.includes(m.domain)) return no("wrong_domain", { domain: m.domain });
  const thumb = await thumbprint(key);
  const [nameUrn, thumbUrn] = m.resources ?? [];
  if (thumbUrn !== THUMB_URN + thumb || !nameUrn?.startsWith(NAME_URN)) return no("wrong_key");
  const name = decodeURIComponent(nameUrn.slice(NAME_URN.length));
  if (m.statement !== directStatement(name, m.address, thumb, m.expirationTime.toISOString())) return no("bad_message");

  const exp = Math.floor(m.expirationTime.getTime() / 1000), iat = Math.floor(m.issuedAt.getTime() / 1000);
  if (exp <= nowSec) return no("expired");
  if (iat > nowSec + SKEW || exp - iat > MAX_LIFE) return no("bad_lifetime");

  let signer;
  try { signer = await recoverMessageAddress({ message, signature: walletSig }); } catch { return no("wrong_wallet"); }
  if (!isAddressEqual(signer, m.address)) return no("wrong_wallet");

  // This site's own origin, fixed at startup, and the challenge it issued. A token made anywhere else fails here.
  const pub = await wc.subtle.importKey("jwk", { kty: "EC", crv: "P-256", x: key.x, y: key.y }, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
  const ok = await wc.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, pub, fromB64(loginSig), loginBytes(origin, challenge, now, claim));
  if (!ok) return no("wrong_nonce");

  const id = parseIdentifier(claim);
  if (!id || id.claim !== claim) return no("bad_claim");
  if (id.kind === "address") {
    if (nameOnly) return no("name_only");
    if (claim !== m.address.toLowerCase()) return no("wrong_wallet");
    return { accepted: true, reason: "ok", mode: "direct", kind: "address", name: claim, address: m.address };
  }
  if (claim !== name) return no("wrong_name");
  let owner;
  try { owner = await lookup.resolve(claim); } catch (e) { return no("lookup_failed", { detail: String(e.message).slice(0, 120) }); }
  if (!owner || !isAddressEqual(owner, m.address)) return no("not_owner", { lookup: lookup.kind });
  return { accepted: true, reason: "ok", mode: "direct", kind: "name", name: claim, address: m.address, lookup: lookup.kind };
}
