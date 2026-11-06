// Issuer. Logic in issuer.mjs. 127.0.0.1 only. Throwaway key, made fresh each start.
// Usage: node issuer/serve.mjs --port 8801 --name alice.eth --owner 0x...
import { createServer } from "node:http";
import { createIssuer, newIssuerKey, Refusal } from "./issuer.mjs";
import { tableLookup } from "../lib/ens-lookup.mjs";
const opt = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const port = Number(opt("port", 8801)), name = opt("name", "alice.eth"), owner = opt("owner");
if (!owner) throw new Error("--owner is required");
const origin = `http://issuer.test:${port}`;
// The wallet signs on the approval page, so that's the domain to pin, the same one sites pin. The issuer has no page of its own now.
const approve = opt("approve-domain", "enroll.test:8806");
const issuer = createIssuer({ key: await newIssuerKey(), lookup: tableLookup({ [name]: owner }), domain: approve, uri: `http://${approve}/`, issuerUrl: `${origin}/`, origin });
const log = (o) => console.log(JSON.stringify({ t: Date.now(), ...o }));
const cors = { "access-control-allow-origin": "*", "cross-origin-resource-policy": "cross-origin" };
createServer((req, res) => {
  const send = (status, obj) => { res.writeHead(status, { "content-type": "application/json", ...cors }); res.end(JSON.stringify(obj)); };
  log({ method: req.method, url: req.url, origin: req.headers.origin ?? null, referer: req.headers.referer ?? null });
  if (req.method === "GET" && req.url === "/nonce") return send(200, { nonce: issuer.newNonce() });
  if (req.method === "GET" && req.url === "/jwks") return send(200, { keys: [issuer.publicJwk] });
  if (req.method === "POST" && req.url === "/issue") {
    let body = "";
    req.on("data", (d) => { body += d; if (body.length > 65536) req.destroy(); });
    req.on("end", async () => {
      try { const r = await issuer.issue(JSON.parse(body)); log({ issued: name, credentials: 2, exp: r.exp }); send(200, r); }
      catch (e) { log({ refused: e.code ?? e.message }); send(e instanceof Refusal ? 403 : 400, { error: e.code ?? "bad_request", why: e.why ?? e.message }); }
    });
    return;
  }
  send(404, { error: "not_found" });
}).listen(port, "127.0.0.1", () => log({ ready: true, port, origin }));
