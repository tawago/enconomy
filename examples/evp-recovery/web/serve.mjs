// One https server on 127.0.0.1:8443 for the two fake hosts, from research live-chrome/serve.mjs. Local only.
//   tawago.test          -> ../issuer/worker.mjs (issuer + fake DNS)
//   recover.tawago.test  -> /, recover.html here; /v1/recovery/* backend; everything else (/app/, /v1/*) core
import https from "node:https";
import http from "node:http";
import { readFileSync } from "node:fs";
import worker from "../issuer/worker.mjs";

const keys = new URL("../.run/keys/", import.meta.url);
const PORT = Number(process.env.PORT ?? 8443);
const BACKEND = Number(process.env.BACKEND_PORT ?? 8100);
const CORE = Number(process.env.CORE_PORT ?? 8001);
const env = {
  ISSUER_HOST: "tawago.test",
  EMAIL: "alice@tawago.test",
  LOGIN_SECRET: "local-test-secret",
  ISSUER_JWK: readFileSync(new URL("issuer.jwk.json", keys), "utf8"),
  FAKE_DNS: "1",
};

function proxy(req, res, port) {
  const up = http.request({ host: "127.0.0.1", port, method: req.method, path: req.url, headers: req.headers }, (r) => {
    res.writeHead(r.statusCode, r.headers);
    r.pipe(res);
  });
  up.on("error", (e) => { res.writeHead(502); res.end(String(e)); });
  req.pipe(up);
}

https.createServer({ key: readFileSync(new URL("tls.key", keys)), cert: readFileSync(new URL("tls.crt", keys)) }, async (req, res) => {
  const host = (req.headers.host ?? "").toLowerCase();
  if (host.startsWith("recover.tawago.test")) {
    if (req.url === "/" || req.url.startsWith("/?") || req.url === "/recover.html") {
      res.writeHead(200, { "content-type": "text/html", "cache-control": "no-store" });
      return res.end(readFileSync(new URL("recover.html", import.meta.url)));
    }
    return proxy(req, res, req.url.startsWith("/v1/recovery/") ? BACKEND : CORE);
  }
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const r = await worker.fetch(new Request(`https://${host}${req.url}`, { method: req.method, headers: req.headers,
    body: req.method === "GET" || req.method === "HEAD" ? undefined : Buffer.concat(chunks) }), env);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(PORT, "127.0.0.1", () => console.log(`https on 127.0.0.1:${PORT}`));
