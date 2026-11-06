// Issuer. Logic in issuer.mjs. 127.0.0.1 only. Throwaway key, made fresh each start, unless --key-file says otherwise.
// Usage: node issuer/serve.mjs --port 8801 --name alice.eth --owner 0x... [--table file.json]
//   --ens deployment --deployment file.json  read ENS at each issue, not a table. Same file as site/serve.mjs. No --name or --owner.
//   --origin https://...  this issuer's public origin, the one K's answer names. Default http://issuer.test:PORT
//   --approve-origin https://...  the approval page's origin, which the wallet message pins. Default http://enroll.test:8806
//   --key-file f  keep the signing key in this file, made on first start, mode 600. A holder's credentials stop working at sites when this key changes.
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { createIssuer, newIssuerKey, loadIssuerKey, Refusal } from "./issuer.mjs";
import { tableLookup, chainLookup } from "../lib/ens-lookup.mjs";
const opt = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const port = Number(opt("port", 8801)), origin = opt("origin", `http://issuer.test:${port}`);
const makeLookup = () => {
  if (opt("ens", "table") === "deployment") { const { rpc, chainId, universalResolver } = JSON.parse(readFileSync(opt("deployment"), "utf8")); return chainLookup({ rpcUrl: rpc, chainId, universalResolver }); }
  if (opt("table")) return tableLookup(opt("table"));
  if (!opt("owner")) throw new Error("--owner is required");
  return tableLookup({ [opt("name", "alice.eth")]: opt("owner") });
};
// The wallet signs on the approval page, so that's the domain to pin, the same one sites pin. The issuer has no page of its own now.
const approve = new URL(opt("approve-origin", "http://enroll.test:8806"));
const issuer = createIssuer({ key: opt("key-file") ? await loadIssuerKey(opt("key-file")) : await newIssuerKey(), lookup: makeLookup(), domain: approve.host, uri: `${approve.origin}/`, issuerUrl: `${origin}/`, origin });
const log = (o) => console.log(JSON.stringify({ t: Date.now(), ...o }));
// no-store: a nonce from a CDN's cache would be someone else's.
const cors = { "access-control-allow-origin": "*", "cross-origin-resource-policy": "cross-origin", "cache-control": "no-store" };
createServer((req, res) => {
  const send = (status, obj) => { res.writeHead(status, { "content-type": "application/json", ...cors }); res.end(JSON.stringify(obj)); };
  log({ method: req.method, url: req.url, origin: req.headers.origin ?? null, referer: req.headers.referer ?? null });
  if (req.method === "GET" && req.url === "/nonce") return send(200, { nonce: issuer.newNonce() });
  if (req.method === "GET" && req.url === "/jwks") return send(200, { keys: [issuer.publicJwk] });
  if (req.method === "POST" && req.url === "/issue") {
    let body = "";
    req.on("data", (d) => { body += d; if (body.length > 65536) req.destroy(); });
    req.on("end", async () => {
      try { const r = await issuer.issue(JSON.parse(body)); log({ issued: true, credentials: 2, exp: r.exp }); send(200, r); }
      catch (e) { log({ refused: e.code ?? e.message }); send(e instanceof Refusal ? 403 : 400, { error: e.code ?? "bad_request", why: e.why ?? e.message }); }
    });
    return;
  }
  send(404, { error: "not_found" });
}).listen(port, "127.0.0.1", () => log({ ready: true, port, origin }));
