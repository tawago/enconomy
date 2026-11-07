// Minimal EVP issuer for one mailbox, ES256 only. Cloudflare Worker module syntax.
// Not deployed. Draft for ETHGlobal Mumbai. See ../evp-flow.md.
//
// Env (Worker secrets / vars):
//   ISSUER_HOST      e.g. "evp.tawago.com" or "<random>.trycloudflare.com"
//   EMAIL            the one address we vouch for, e.g. "alice@tawago.com"
//   LOGIN_SECRET     shared secret for /login (hackathon only; passkey is the upgrade)
//   ISSUER_JWK       private P-256 JWK as JSON string (kty, crv, x, y, d)
//   FAKE_DNS         "1" to serve /dns?name=... in dns.google JSON shape (tunnel tests only)
//
// Routes (all on ISSUER_HOST unless noted):
//   GET  /.well-known/email-verification   issuer metadata
//   GET  /.well-known/web-identity         FedCM well-known. Chrome fetches it at the eTLD+1,
//                                          so for evp.tawago.com it must ALSO be routed at tawago.com.
//   GET  /jwks                             public key
//   GET  /accounts                         FedCM accounts list (needs session cookie)
//   GET  /login, POST /login               sets session cookie + Set-Login: logged-in
//   POST /issue                            EVT issuance (cookie + RFC 9421 signature)
//   GET  /dns?name=...                     fake dns.google JSON (only if FAKE_DNS=1)

const enc = new TextEncoder();
const b64u = (u8) => btoa(String.fromCharCode(...new Uint8Array(u8))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const json = (obj, extra = {}, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json", ...extra } });

async function sessionToken(env) {
  // Stateless session: HMAC(LOGIN_SECRET, EMAIL). One user, so this is enough for a demo.
  const k = await crypto.subtle.importKey("raw", enc.encode(env.LOGIN_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64u(await crypto.subtle.sign("HMAC", k, enc.encode("evp-session:" + env.EMAIL)));
}
async function loggedIn(req, env) {
  const c = req.headers.get("cookie") || "";
  const m = c.match(/(?:^|;\s*)evp_session=([^;]+)/);
  return !!m && m[1] === (await sessionToken(env));
}

// --- RFC 9421 check of Chrome's request (hwk Signature-Key, ES256 only) ---
// Chrome covers: "@method" "@authority" "@path" "content-digest" "signature-key";created=N
// Source: chromium content/browser/webid/delegation/email_verification_request.cc
async function verifyChromeSignature(req, body, host) {
  const digestHdr = req.headers.get("content-digest") || "";
  const sigKey = req.headers.get("signature-key") || "";
  const sigInput = req.headers.get("signature-input") || "";
  const sig = req.headers.get("signature") || "";

  // 1. Content-Digest over the raw body bytes.
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", body));
  const m1 = digestHdr.match(/sha-256=:([^:]+):/);
  if (!m1 || m1[1] !== btoa(String.fromCharCode(...d))) return { ok: false, why: "content-digest" };

  // 2. Signature-Key: sig=hwk;alg="ES256";crv="P-256";kty="EC";x="..";y=".."
  const p = Object.fromEntries([...sigKey.matchAll(/;(\w+)="([^"]*)"/g)].map((m) => [m[1], m[2]]));
  if (!sigKey.startsWith("sig=hwk") || p.kty !== "EC" || p.crv !== "P-256") return { ok: false, why: "signature-key not P-256" };
  if (p.alg && p.alg !== "ES256") return { ok: false, why: "alg" };

  // 3. created within 300 s (draft-02).
  const mi = sigInput.match(/^sig=(\(.*\));created=(\d+)$/);
  if (!mi) return { ok: false, why: "signature-input" };
  if (Math.abs(Date.now() / 1000 - Number(mi[2])) > 300) return { ok: false, why: "created" };

  // 4. Rebuild the signature base exactly like Chrome does.
  const url = new URL(req.url);
  const base =
    `"@method": POST\n` +
    `"@authority": ${host}\n` +
    `"@path": ${url.pathname}\n` +
    `"content-digest": ${digestHdr}\n` +
    `"signature-key": ${sigKey}\n` +
    `"@signature-params": ${mi[1]};created=${mi[2]}`;
  const ms = sig.match(/^sig=:([^:]+):$/);
  if (!ms) return { ok: false, why: "signature" };
  const key = await crypto.subtle.importKey("jwk", { kty: "EC", crv: "P-256", x: p.x, y: p.y }, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, b64(ms[1]), enc.encode(base));
  return ok ? { ok: true, jwk: { kty: "EC", crv: "P-256", x: p.x, y: p.y } } : { ok: false, why: "bad signature" };
}

async function signEvt(env, payload) {
  const jwk = JSON.parse(env.ISSUER_JWK);
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const header = { alg: "ES256", typ: "evt+jwt", kid: "tawago-1" };
  const input = b64u(enc.encode(JSON.stringify(header))) + "." + b64u(enc.encode(JSON.stringify(payload)));
  // WebCrypto ECDSA output is already raw r||s (64 bytes), which is what JWS ES256 wants.
  const s = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(input));
  return input + "." + b64u(s) + "~"; // SD-JWT, zero disclosures, trailing tilde required
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const ORIGIN = "https://" + env.ISSUER_HOST;

    switch (`${req.method} ${url.pathname}`) {
      case "GET /.well-known/email-verification":
        return json({
          issuer: ORIGIN,
          issuance_endpoint: ORIGIN + "/issue",
          jwks_uri: ORIGIN + "/jwks",
          // ES256 first and alone: Chrome then makes a P-256 browser key (first known entry wins).
          signing_alg_values_supported: ["ES256"],
        });

      case "GET /.well-known/web-identity":
        // Served at the eTLD+1. Both URLs must be same-origin with the issuer for EVP's accounts check.
        return json({ accounts_endpoint: ORIGIN + "/accounts", login_url: ORIGIN + "/login" });

      case "GET /jwks": {
        const { kty, crv, x, y } = JSON.parse(env.ISSUER_JWK);
        return json({ keys: [{ kty, crv, x, y, kid: "tawago-1", alg: "ES256", use: "sig" }] });
      }

      case "GET /accounts":
        if (!(await loggedIn(req, env))) return json({ accounts: [] }, { "set-login": "logged-out" });
        return json({ accounts: [{ id: "1", email: env.EMAIL, name: env.EMAIL }] });

      case "GET /login":
        return new Response(
          `<!doctype html><form method=post><input name=secret type=password autofocus><button>Sign in to ${env.ISSUER_HOST}</button></form>`,
          { headers: { "content-type": "text/html" } });

      case "POST /login": {
        const f = await req.formData();
        if (f.get("secret") !== env.LOGIN_SECRET) return new Response("no", { status: 403 });
        const tok = await sessionToken(env);
        return new Response("signed in. close this tab.", {
          headers: {
            "content-type": "text/plain",
            // Cross-site fetches from the RP page need SameSite=None; Secure (Chrome issuer guide).
            "set-cookie": `evp_session=${tok}; Path=/; Secure; HttpOnly; SameSite=None; Max-Age=86400`,
            "set-login": "logged-in",
          },
        });
      }

      case "POST /issue": {
        const dest = req.headers.get("sec-fetch-dest");
        if (dest !== "email-verification" && dest !== "emailverification") return json({ error: "invalid_request" }, {}, 400);
        if (!(await loggedIn(req, env))) return json({ error: "authentication_required" }, {}, 401);
        const body = await req.arrayBuffer();
        const v = await verifyChromeSignature(req, body, env.ISSUER_HOST);
        if (!v.ok) return json({ error: "invalid_request", why: v.why }, {}, 400);
        const { email } = JSON.parse(new TextDecoder().decode(body));
        if (typeof email !== "string" || email.toLowerCase() !== env.EMAIL.toLowerCase())
          return json({ error: "authentication_required" }, {}, 401);
        const iat = Math.floor(Date.now() / 1000);
        // email echoed byte-for-byte (Chrome 156+ checks this).
        const token = await signEvt(env, { iss: ORIGIN, iat, exp: iat + 300, cnf: { jwk: v.jwk }, email, email_verified: true });
        return json({ issuance_token: token });
      }

      case "GET /dns": {
        // Stand-in for https://dns.google/resolve?type=txt&do=1&name=...
        // Only used with chrome --dns-txt-resolver-url-prefix=https://<host>/dns?name=
        if (env.FAKE_DNS !== "1") return new Response("off", { status: 404 });
        return json({ Status: 0, Answer: [{ name: url.searchParams.get("name") + ".", type: 16, TTL: 60, data: "iss=" + env.ISSUER_HOST }] },
          { "access-control-allow-origin": "*" });
      }
    }
    return new Response("not found", { status: 404 });
  },
};
