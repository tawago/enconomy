// Minimal IDKit v4 sidecar. Binds 127.0.0.1 only. The Python server is the only client.
// POST /requests {app_id, action, signal, rp_context, return_to?, environment?} -> {request_id, connector_uri}
// GET  /requests/:id -> {status, error?, result?}   (result = IDKitResult, forward unchanged to Portal /api/v4/verify/{rp_id})
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init) => {
  if (input instanceof URL && input.protocol === "file:")
    return new Response(readFileSync(fileURLToPath(input)), { headers: { "content-type": "application/wasm" } });
  return realFetch(input, init);
};
const { IDKit, proofOfHuman } = await import("@worldcoin/idkit-core");
const reqs = new Map(); // request_id -> {req, created}
const TTL_MS = 10 * 60 * 1000;
setInterval(() => { const now = Date.now(); for (const [k, v] of reqs) if (now - v.created > TTL_MS) reqs.delete(k); }, 60_000).unref();
const body = (r) => new Promise((ok, no) => { let b = ""; r.on("data", c => b += c); r.on("end", () => { try { ok(JSON.parse(b || "{}")); } catch (e) { no(e); } }); });
const send = (res, code, obj) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(obj)); };
createServer(async (r, res) => {
  try {
    if (r.method === "GET" && r.url === "/health") return send(res, 200, { ok: true, idkit: "4.2.4" });
    if (r.method === "POST" && r.url === "/requests") {
      const b = await body(r);
      const req = await IDKit.request({ app_id: b.app_id, action: b.action, rp_context: b.rp_context,
        allow_legacy_proofs: false, environment: b.environment ?? "production", return_to: b.return_to })
        .preset(proofOfHuman({ signal: b.signal }));
      reqs.set(req.requestId, { req, created: Date.now() });
      return send(res, 200, { request_id: req.requestId, connector_uri: req.connectorURI });
    }
    const m = r.method === "GET" && r.url.match(/^\/requests\/([0-9a-f-]{36})$/);
    if (m) {
      const e = reqs.get(m[1]); if (!e) return send(res, 404, { error: "unknown_request" });
      if (e.terminal) return send(res, 200, e.terminal);   // terminal entries stay until TTL: GET is idempotent
      const st = await e.req.pollOnce();
      const out = { status: st.type, error: st.error ?? null, result: st.result ?? null };
      if (st.type === "confirmed" || st.type === "failed") e.terminal = out;
      return send(res, 200, out);
    }
    send(res, 404, { error: "not_found" });
  } catch (e) { send(res, 500, { error: String(e?.message ?? e) }); }
}).listen(Number(process.env.PORT ?? 8787), "127.0.0.1", () => console.error("idkit-sidecar up"));
