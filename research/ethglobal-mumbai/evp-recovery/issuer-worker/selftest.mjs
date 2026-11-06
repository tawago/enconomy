// Plays Chrome against worker.mjs in plain Node 24 (no wrangler, no network).
// Builds the request the way chromium email_verification_request.cc does, then checks
// the EVT the way evt_verifier.cc + EvpVerifier.sol expect it. Fresh test keys every run.
import worker from "./worker.mjs";
import { webcrypto as C, createHash } from "node:crypto";

const b64u = (u) => Buffer.from(u).toString("base64url");
const b64 = (u) => Buffer.from(u).toString("base64");
let fail = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fail++; };

const issuerKp = await C.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
const env = {
  ISSUER_HOST: "evp.tawago.com",
  EMAIL: "alice@tawago.com",
  LOGIN_SECRET: "test-secret-" + Math.random(),
  ISSUER_JWK: JSON.stringify(await C.subtle.exportKey("jwk", issuerKp.privateKey)),
  FAKE_DNS: "1",
};
const H = "https://" + env.ISSUER_HOST;
const call = (path, init = {}) => worker.fetch(new Request(H + path, init), env);

// discovery
const wk = await (await call("/.well-known/email-verification")).json();
ok(wk.issuer === H && wk.signing_alg_values_supported[0] === "ES256", "well-known issuer + ES256");
const wi = await (await call("/.well-known/web-identity")).json();
ok(new URL(wi.accounts_endpoint).origin === H && wi.login_url, "web-identity direct format, same-origin accounts");
const dns = await (await call("/dns?name=_email-verification.tawago.com")).json();
ok(dns.Status === 0 && dns.Answer[0].type === 16 && dns.Answer[0].data === "iss=evp.tawago.com", "fake DoH shape matches dns.google");

// login
let r = await call("/accounts");
ok((await r.json()).accounts.length === 0, "accounts empty when logged out");
const fd = new FormData(); fd.set("secret", env.LOGIN_SECRET);
r = await call("/login", { method: "POST", body: fd });
const setCookie = r.headers.get("set-cookie");
ok(/SameSite=None/.test(setCookie) && r.headers.get("set-login") === "logged-in", "login sets SameSite=None cookie + Set-Login");
const cookie = setCookie.split(";")[0];
r = await call("/accounts", { headers: { cookie } });
ok((await r.json()).accounts[0].email === env.EMAIL, "accounts lists the email");

// Chrome-like issuance request
async function chromeRequest(email, { tamperBody = false, created = Math.floor(Date.now() / 1000) } = {}) {
  const kp = await C.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
  const pub = await C.subtle.exportKey("jwk", kp.publicKey);
  const body = JSON.stringify({ email });
  const digest = `sha-256=:${b64(createHash("sha256").update(body).digest())}:`;
  // ToDict() of the JWK is a sorted dict: alg, crv, kty, x, y
  const sigKey = `sig=hwk;alg="ES256";crv="P-256";kty="EC";x="${pub.x}";y="${pub.y}"`;
  const params = `("@method" "@authority" "@path" "content-digest" "signature-key");created=${created}`;
  const base = `"@method": POST\n"@authority": evp.tawago.com\n"@path": /issue\n"content-digest": ${digest}\n"signature-key": ${sigKey}\n"@signature-params": ${params}`;
  const sig = new Uint8Array(await C.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, kp.privateKey, new TextEncoder().encode(base)));
  const req = {
    method: "POST",
    headers: {
      cookie, "content-type": "application/json", accept: "application/json", "sec-fetch-dest": "email-verification",
      "content-digest": digest, "signature-key": sigKey, "signature-input": `sig=${params}`, signature: `sig=:${b64(sig)}:`,
    },
    body: tamperBody ? JSON.stringify({ email: "mallory@tawago.com" }) : body,
  };
  return { req, pub };
}

const { req, pub } = await chromeRequest("Alice@tawago.com");
r = await call("/issue", req);
const out = await r.json();
ok(r.status === 200 && out.issuance_token.endsWith("~"), "issue 200, trailing tilde");
const [h, p, s] = out.issuance_token.slice(0, -1).split(".");
const hdr = JSON.parse(Buffer.from(h, "base64url")), pl = JSON.parse(Buffer.from(p, "base64url"));
ok(hdr.typ === "evt+jwt" && hdr.alg === "ES256", "EVT header typ/alg");
ok(pl.email === "Alice@tawago.com", "email echoed byte-for-byte (not lowercased)");
ok(pl.cnf.jwk.x === pub.x && pl.cnf.jwk.y === pub.y, "cnf.jwk = browser key from Signature-Key");
ok(pl.iss === H && pl.email_verified === true, "iss + email_verified");
const vk = await C.subtle.importKey("jwk", (await (await call("/jwks")).json()).keys[0], { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
ok(await C.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, vk, Buffer.from(s, "base64url"), new TextEncoder().encode(h + "." + p)), "EVT signature verifies with JWKS");

// negatives
r = await call("/issue", (await chromeRequest("alice@tawago.com", { tamperBody: true })).req);
ok(r.status === 400, "tampered body rejected (content-digest)");
r = await call("/issue", (await chromeRequest("alice@tawago.com", { created: Math.floor(Date.now() / 1000) - 400 })).req);
ok(r.status === 400, "stale created rejected");
const noCookie = (await chromeRequest("alice@tawago.com")).req; delete noCookie.headers.cookie;
r = await call("/issue", noCookie);
ok(r.status === 401, "no session -> authentication_required");
r = await call("/issue", (await chromeRequest("bob@tawago.com")).req);
ok(r.status === 401, "other mailbox -> authentication_required");

console.log(fail ? `${fail} FAILED` : "all passed");
process.exit(fail ? 1 : 0);
