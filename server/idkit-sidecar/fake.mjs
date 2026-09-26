// Fake IDKit sidecar for tests and the A2 live test. Same HTTP API as idkit-sidecar.mjs, no network, no deps.
// Use ONLY with a server started with POP_WORLDID_FAKE=1 (doc 01 §6.10). Binds 127.0.0.1.
// Env: PORT (8787), FAKE_POLLS (2 non-terminal polls before confirmed), FAKE_SAME_HUMAN=1 (both roles get one nullifier),
//      FAKE_REJECT=1 (terminal failed/user_rejected instead of confirmed).
import { createServer } from "node:http";
import { createHash, randomUUID } from "node:crypto";
const TTL_MS = 10 * 60 * 1000, POLLS = Number(process.env.FAKE_POLLS ?? 2);
const reqs = new Map();
setInterval(() => { const now = Date.now(); for (const [k, v] of reqs) if (now - v.created > TTL_MS) reqs.delete(k); }, 60_000).unref();
const body = (r) => new Promise((ok, no) => { let b = ""; r.on("data", c => b += c); r.on("end", () => { try { ok(JSON.parse(b || "{}")); } catch (e) { no(e); } }); });
const send = (res, code, obj) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(obj)); };
// nullifier: 0x00 + 31 bytes of sha256("fake-human:<who>:<action>"), so it is < 2^248 like a field element
const nullifier = (who, action) => "0x00" + createHash("sha256").update(`fake-human:${who}:${action}`).digest("hex").slice(0, 62);
createServer(async (r, res) => {
  try {
    if (r.method === "GET" && r.url === "/health") return send(res, 200, { ok: true, idkit: "fake" });
    if (r.method === "POST" && r.url === "/requests") {
      const b = await body(r);
      const id = randomUUID();
      const role = String(b.signal ?? "").slice(-2) === "41" ? "A" : "B";   // signal = 0x<nonce32><role byte>
      reqs.set(id, { b, role, polls: 0, created: Date.now(), terminal: null });
      return send(res, 200, { request_id: id, connector_uri: `https://world.org/verify?fake=1&t=${id}` });
    }
    const m = r.method === "GET" && r.url.match(/^\/requests\/([0-9a-f-]{36})$/);
    if (m) {
      const e = reqs.get(m[1]); if (!e) return send(res, 404, { error: "unknown_request" });
      if (e.terminal) return send(res, 200, e.terminal);                    // terminal entries stay until TTL (idempotent GET)
      e.polls += 1;
      if (e.polls <= POLLS) return send(res, 200, { status: e.polls === 1 ? "waiting_for_connection" : "awaiting_confirmation", error: null, result: null });
      if (process.env.FAKE_REJECT === "1") e.terminal = { status: "failed", error: "user_rejected", result: null };
      else {
        const who = process.env.FAKE_SAME_HUMAN === "1" ? "X" : e.role;
        e.terminal = { status: "confirmed", error: null, result: {
          protocol_version: "4.0", nonce: e.b.rp_context.nonce, action: e.b.action, environment: "fake",
          responses: [{ identifier: "proof_of_human", issuer_schema_id: 1, nullifier: nullifier(who, e.b.action),
                        expires_at_min: e.b.rp_context.created_at, proof: ["1", "2", "3", "4", "5"] }] } };
      }
      return send(res, 200, e.terminal);
    }
    send(res, 404, { error: "not_found" });
  } catch (e) { send(res, 500, { error: String(e?.message ?? e) }); }
}).listen(Number(process.env.PORT ?? 8787), "127.0.0.1", () => console.error("fake idkit-sidecar up (TEST ONLY)"));
