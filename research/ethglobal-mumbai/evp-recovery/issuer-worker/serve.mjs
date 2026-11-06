// Local runner, no deps. Wraps worker.mjs (issuer) or rp.html (recovery page) in node:http
// so cloudflared quick tunnels can expose them. Not deployed anywhere.
//
//   node keygen.mjs > keys/issuer.jwk.json          (once; fresh test key, gitignored)
//   ISSUER_HOST=<issuer-tunnel-host> EMAIL=alice@tawago.com LOGIN_SECRET=... FAKE_DNS=1 \
//     node serve.mjs issuer 8787
//   node serve.mjs rp 8788
import http from "node:http";
import { readFileSync } from "node:fs";
import worker from "./worker.mjs";

const [mode = "issuer", port = "8787"] = process.argv.slice(2);
const here = new URL(".", import.meta.url);

const server = http.createServer(async (req, res) => {
  // cloudflared forwards the public Host header, so the URL matches what Chrome signed.
  const url = `https://${req.headers.host}${req.url}`;
  if (mode === "rp") {
    if (req.url === "/" || req.url.startsWith("/?")) {
      res.writeHead(200, { "content-type": "text/html" });
      return res.end(readFileSync(new URL("rp.html", here)));
    }
    res.writeHead(404); return res.end();
  }
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;
  const env = {
    ISSUER_HOST: process.env.ISSUER_HOST,
    EMAIL: process.env.EMAIL,
    LOGIN_SECRET: process.env.LOGIN_SECRET,
    ISSUER_JWK: process.env.ISSUER_JWK ?? readFileSync(new URL("keys/issuer.jwk.json", here), "utf8"),
    FAKE_DNS: process.env.FAKE_DNS ?? "0",
  };
  const r = await worker.fetch(new Request(url, { method: req.method, headers: req.headers, body: req.method === "GET" ? undefined : body }), env);
  console.log(new Date().toISOString(), req.method, req.url, "->", r.status, req.headers["sec-fetch-dest"] ?? "");
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
});
server.listen(Number(port), "127.0.0.1", () => console.log(`${mode} on http://127.0.0.1:${port}`));
