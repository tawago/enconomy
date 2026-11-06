// One https server on 127.0.0.1:8443 for two fake hosts. No deps.
//   tawago.test          -> ../issuer-worker/worker.mjs (issuer + fake dns.google JSON)
//   recover.tawago.test  -> rp.html (the recovery page)
// Chrome reaches it via --host-resolver-rules "MAP *.tawago.test 127.0.0.1:8443".
// Every request is logged with full headers + body to tmp/requests.jsonl.
import https from "node:https";
import { readFileSync, appendFileSync } from "node:fs";
import worker from "../issuer-worker/worker.mjs";

const here = new URL(".", import.meta.url);
const tmp = new URL("tmp/", here);
const PORT = Number(process.env.PORT ?? 8443);
const env = {
  ISSUER_HOST: "tawago.test",
  EMAIL: "alice@tawago.test",
  LOGIN_SECRET: "local-test-secret",
  ISSUER_JWK: readFileSync(new URL("keys/issuer.jwk.json", tmp), "utf8"),
  FAKE_DNS: "1",
};
const log = (o) => appendFileSync(new URL("requests.jsonl", tmp), JSON.stringify(o) + "\n");

const server = https.createServer(
  { key: readFileSync(new URL("keys/tls.key", tmp)), cert: readFileSync(new URL("keys/tls.crt", tmp)) },
  async (req, res) => {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const body = chunks.length ? Buffer.concat(chunks) : undefined;
    const host = (req.headers.host ?? "").toLowerCase();
    let status, headers, out;
    if (host.startsWith("recover.tawago.test")) {
      // CSP_MODE (REFUTE.md section 5): unset = no CSP header (the 13-token run).
      //   self  = header "default-src 'self'", page script moved to /rp.js (DESIGN section 9: no inline)
      //   nonce = header "script-src 'nonce-<random>'", inline script carries that nonce
      const mode = process.env.CSP_MODE ?? "";
      const html = readFileSync(new URL("rp.html", here), "utf8");
      const js = html.slice(html.indexOf("<script>") + 8, html.indexOf("</script>"));
      if (req.url === "/" || req.url.startsWith("/?")) {
        status = 200; headers = { "content-type": "text/html" };
        if (mode === "self") {
          headers["content-security-policy"] = "default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'";
          out = Buffer.from(html.replace(/<script>[\s\S]*<\/script>/, '<script src="/rp.js"></script>'));
        } else if (mode === "nonce") {
          const n = Math.random().toString(36).slice(2);
          headers["content-security-policy"] = `script-src 'nonce-${n}'; object-src 'none'; base-uri 'none'`;
          out = Buffer.from(html.replace("<script>", `<script nonce="${n}">`));
        } else out = Buffer.from(html);
      } else if (req.url === "/rp.js") {
        status = 200; headers = { "content-type": "text/javascript" }; out = Buffer.from(js);
      } else { status = 404; headers = {}; out = Buffer.alloc(0); }
    } else {
      const r = await worker.fetch(
        new Request(`https://${host}${req.url}`, { method: req.method, headers: req.headers, body: req.method === "GET" || req.method === "HEAD" ? undefined : body }),
        env);
      status = r.status; headers = Object.fromEntries(r.headers); out = Buffer.from(await r.arrayBuffer());
    }
    log({ t: new Date().toISOString(), method: req.method, host, url: req.url, headers: req.headers,
          body: body?.toString("utf8"), status, resHeaders: headers, res: out.length < 4000 ? out.toString("utf8") : `(${out.length} bytes)` });
    console.log(new Date().toISOString(), req.method, host + req.url, "->", status, req.headers["sec-fetch-dest"] ?? "");
    res.writeHead(status, headers);
    res.end(out);
  });
server.listen(PORT, "127.0.0.1", () => console.log(`https on 127.0.0.1:${PORT}`));
