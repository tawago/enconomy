// Stands in for a key CDN. Local files, 127.0.0.1 only. Only serves the two proving keys. A CDN would need these same CORS and CORP headers.
import { createServer } from "node:http";
import { createReadStream, statSync } from "node:fs";
import { basename, join } from "node:path";
import { thirdParty } from "../lib/third-party.mjs";
const KEYS = thirdParty("keys");
const OK = new Set(["1k_prepare_proving.key", "1k_show_proving.key"]);
const port = Number(process.argv[2] ?? 8804);
createServer((req, res) => {
  const f = basename(new URL(req.url, "http://x").pathname);
  console.log(JSON.stringify({ t: Date.now(), method: req.method, url: req.url, origin: req.headers.origin ?? null, referer: req.headers.referer ?? null }));
  if (!OK.has(f)) { res.writeHead(404); return res.end(); }
  const p = join(KEYS, f);
  res.writeHead(200, { "content-type": "application/octet-stream", "content-length": statSync(p).size, "access-control-allow-origin": "*", "cross-origin-resource-policy": "cross-origin", "cache-control": "max-age=31536000, immutable" });
  createReadStream(p).pipe(res);
}).listen(port, "127.0.0.1", () => console.log(JSON.stringify({ ready: true, port })));
