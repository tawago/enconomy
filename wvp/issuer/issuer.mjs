// Thin issuer. Only anonymous login needs it. Checks one wallet signature, K's answer to a nonce and one ENS lookup, then signs ES256 SD-JWTs over K, in the JWT shape OpenAC's circuit reads.
// One signature gets two credentials over the same K: one whose name slot is the ENS name, one whose name slot is the address.
// No new keys, no new circuit. Same shape check on both.
import { randomBytes, webcrypto, createHash } from "node:crypto";
import { recoverMessageAddress, isAddressEqual, getAddress } from "viem";
import { createSiweMessage, parseSiweMessage } from "viem/siwe";
import { nameDigest, normalizeName, thumbprint, THUMB_URN, NAME_URN } from "../lib/wvp.mjs";
import { payloadProblem } from "../lib/payload-check.mjs";
import { parseIdentifier, addressSlot } from "../lib/identifier.mjs";
import { directStatement, issueBytes } from "../lib/direct.mjs";

const subtle = webcrypto.subtle;
const enc = new TextEncoder();
const b64u = (b) => Buffer.from(b).toString("base64url");
export const DAY = 86400;
const HOUR = 3600;

export class Refusal extends Error {
  constructor(code, why) { super(`${code}: ${why}`); this.code = code; this.why = why; }
}
const refuse = (code, why) => { throw new Refusal(code, why); };

export async function newIssuerKey() {
  const k = await subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
  const { kty, crv, x, y } = await subtle.exportKey("jwk", k.publicKey);
  return { privateKey: k.privateKey, publicJwk: { kty, crv, x, y } };
}

async function checkDeviceKey(jwk) {
  if (!jwk || jwk.kty !== "EC" || jwk.crv !== "P-256") refuse("bad_device_key", "not a P-256 JWK");
  for (const c of ["x", "y"]) if (typeof jwk[c] !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(jwk[c])) refuse("bad_device_key", `${c} is not 32 bytes of base64url`);
  // Refuses points that aren't on the curve.
  try { await subtle.importKey("jwk", { kty: "EC", crv: "P-256", x: jwk.x, y: jwk.y }, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]); }
  catch { refuse("bad_device_key", "point is not on P-256"); }
}

// domain and uri pin the approval page, the same one sites pin. origin is this issuer, the one K's answer names.
export function createIssuer({ key, lookup, domain, uri, chainId = 1, clock = () => Math.floor(Date.now() / 1000), nonceTtl = 300, credTtl = DAY, issuerUrl = uri, origin = issuerUrl, maxLife = 7 * DAY }) {
  const nonces = new Map(); // nonce -> expiry, deleted on use

  function newNonce() {
    const nonce = randomBytes(16).toString("hex");
    nonces.set(nonce, clock() + nonceTtl);
    return nonce;
  }

  // slot is the string behind the name slot's digest: an ENS name, or the address with its prefix.
  async function signCredential({ slot, deviceKey, exp, now }) {
    // Claim values are strings of digits, which is what the circuit's uint rule accepts.
    const claim = (k, v) => b64u(enc.encode(JSON.stringify([randomBytes(18).toString("base64url"), k, v])));
    const disclosures = [claim("name", String(nameDigest(slot))), claim("exp", String(exp))];
    const header = { alg: "ES256", typ: "vc+sd-jwt" };
    const digests = disclosures.map((d) => createHash("sha256").update(d).digest("base64url"));
    // No "sub", on purpose. The holder picks the name, and signed holder text can carry a forged digest. That was a real hole: wvp/README.md, "The forged digest".
    // The name is only ever signed as its digest, inside a disclosure.
    const payload = {
      iss: issuerUrl, nbf: now, exp,
      cnf: { jwk: { kty: "EC", crv: "P-256", x: deviceKey.x, y: deviceKey.y } },
      vc: {
        "@context": ["https://www.w3.org/2018/credentials/v1"], type: ["VerifiableCredential"],
        credentialSubject: { _sd: digests, _sd_alg: "sha-256" },
      },
    };
    const payloadJson = JSON.stringify(payload);
    const problem = payloadProblem(payloadJson, { x: deviceKey.x, y: deviceKey.y, digests });
    if (problem) refuse("unsafe_payload", problem);
    const input = b64u(enc.encode(JSON.stringify(header))) + "." + b64u(enc.encode(payloadJson));
    const sig = await subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key.privateKey, enc.encode(input));
    return [input + "." + b64u(new Uint8Array(sig)), ...disclosures, ""].join("~");
  }

  // The wallet signature was made once, maybe with the issuer down, so it can't hold this issuer's nonce. So K answers the nonce instead.
  async function issue({ message, signature, deviceKey, issueNonce, proof }) {
    if (typeof message !== "string" || typeof signature !== "string") refuse("bad_request", "message and signature are required");
    if (typeof issueNonce !== "string" || typeof proof !== "string") refuse("no_key_proof", "K must answer a nonce from this issuer");
    await checkDeviceKey(deviceKey);

    const m = parseSiweMessage(message);
    for (const f of ["address", "domain", "uri", "version", "chainId", "nonce", "issuedAt", "expirationTime", "statement"])
      if (m[f] === undefined) refuse("bad_message", `missing ${f}`);
    // Reject anything the parser would have skipped over.
    let rebuilt = null;
    try { rebuilt = createSiweMessage(m); } catch (e) { refuse("bad_message", e.shortMessage ?? e.message); }
    if (rebuilt !== message) refuse("bad_message", "not in canonical ERC-4361 form");

    // 1. Who signed.
    let signer;
    try { signer = await recoverMessageAddress({ message, signature }); }
    catch { refuse("bad_signature", "signature does not parse"); }
    if (!isAddressEqual(signer, m.address)) refuse("bad_signature", `signed by ${signer}, message says ${m.address}`);

    // 2. Was it signed for us.
    if (m.domain !== domain) refuse("domain_mismatch", `message is for ${m.domain}, this issuer is ${domain}`);
    if (m.uri !== uri) refuse("domain_mismatch", `message URI is ${m.uri}, this issuer is ${uri}`);
    if (m.chainId !== chainId) refuse("chain_mismatch", `message chain ${m.chainId}, want ${chainId}`);
    if (m.version !== "1") refuse("bad_message", `version ${m.version}`);

    // 3. Is it still good.
    const now = clock();
    const expSec = Math.floor(m.expirationTime.getTime() / 1000);
    if (expSec <= now) refuse("siwe_expired", `message expired at ${m.expirationTime.toISOString()}`);
    if (m.issuedAt.getTime() / 1000 > now + 60) refuse("bad_message", "issued in the future");
    if (m.notBefore && m.notBefore.getTime() / 1000 > now) refuse("siwe_not_yet_valid", "notBefore is in the future");
    if (expSec - m.issuedAt.getTime() / 1000 > maxLife) refuse("bad_message", "approval lasts too long");

    // 4. Does it approve this K for this name, in words the wallet showed.
    const res = m.resources ?? [];
    const nameRes = res.find((r) => r.startsWith(NAME_URN)), keyRes = res.find((r) => r.startsWith(THUMB_URN));
    if (res.length !== 2 || !nameRes || !keyRes) refuse("bad_message", "resources must be the name and the key thumbprint");
    const rawName = decodeURIComponent(nameRes.slice(NAME_URN.length));
    let name;
    try { name = normalizeName(rawName); } catch { refuse("bad_name", `${rawName} does not normalize`); }
    if (name !== rawName) refuse("bad_name", `${rawName} is not normalized`);
    // A name can't pose as an address, or the two slots would blur.
    if (parseIdentifier(name)?.kind !== "name") refuse("bad_name", `${rawName} is not an ENS name`);
    const thumb = thumbprint(deviceKey);
    if (keyRes.slice(THUMB_URN.length) !== thumb) refuse("key_mismatch", "wallet approved a different key");
    if (m.statement !== directStatement(name, m.address, thumb, m.expirationTime.toISOString())) refuse("bad_message", "statement does not match");

    // 5. K itself is here. A site holds the wallet signature and K's public key, not K, so it stops at this step.
    let held = false;
    try {
      const pub = await subtle.importKey("jwk", { kty: "EC", crv: "P-256", x: deviceKey.x, y: deviceKey.y }, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
      held = await subtle.verify({ name: "ECDSA", hash: "SHA-256" }, pub, Buffer.from(proof, "base64url"), issueBytes(origin, issueNonce));
    } catch {}
    if (!held) refuse("no_key_proof", "K didn't answer this nonce");

    // 6. One time only. Checked and used with no await in between. Only signed, in-date, on-domain messages from the holder of K get
    // this far, so a stranger can't burn someone's nonce.
    const nonceExp = nonces.get(issueNonce);
    if (nonceExp === undefined) refuse("nonce_unknown_or_used", "this issuer did not hand out this nonce, or it was already used");
    nonces.delete(issueNonce);
    if (nonceExp <= now) refuse("nonce_expired", "nonce is too old");

    // 7. ENS.
    let owner;
    try { owner = await lookup.resolve(name); }
    catch (e) { refuse("ens_lookup_failed", e.shortMessage ?? e.message); }
    if (!owner) refuse("ens_no_address", `${name} has no address record`);
    if (!isAddressEqual(getAddress(owner), signer)) refuse("ens_mismatch", `${name} points to ${owner}, signer is ${signer}`);

    // Expiry rounds down to the hour, so it's a weaker fingerprint if a site ever learns it.
    const exp = Math.floor(Math.min(expSec, now + credTtl) / HOUR) * HOUR;
    if (exp <= now) refuse("siwe_expired", "under an hour left");
    // Both only ever reach the signed text as a digest of a digest. Each gets fresh salts, so the two share no disclosure.
    const sdJwt = await signCredential({ slot: name, deviceKey, exp, now });
    const sdJwtAddress = await signCredential({ slot: addressSlot(signer), deviceKey, exp, now });
    return { sdJwt, sdJwtAddress, exp };
  }

  return { newNonce, issue, publicJwk: key.publicJwk };
}
