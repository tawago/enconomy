# stands in for GET /v1/session/{sid}/attestation (proposed WID-S.6 + pool block)
import hashlib, json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as HTTPServer
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes
K = ec.derive_private_key(0xC0FFEE, ec.SECP256R1())
import os; POOL = os.environ["POOL"]; CHAIN = 480; T0 = time.time()
def att(sid, leaf, verdict, ready_after):
    if time.time() - T0 < ready_after: return {"session_id": sid, "state": "running"}
    out = {"session_id": sid, "state": "done", "verdict": verdict}
    if verdict != "NEAR": return out
    pair, exp = hashlib.sha256(sid.encode()).digest(), int(time.time()) + 600
    pre = b"pop-pool-v1" + CHAIN.to_bytes(32,"big") + bytes.fromhex(POOL[2:]) + leaf.to_bytes(32,"big") + pair + exp.to_bytes(8,"big")
    r, s = utils.decode_dss_signature(K.sign(hashlib.sha256(pre).digest(), ec.ECDSA(utils.Prehashed(hashes.SHA256()))))
    out["consumer"] = {"kind": "pool-xfer", "chain_id": CHAIN, "address": POOL, "leaf": hex(leaf),
        "att": {"v": "pop-pool-v1", "pair_tag": "0x"+pair.hex(), "expiry": exp, "r": "0x%064x"%r, "s": "0x%064x"%s}}
    return out
S = {"s1": (1001, "NEAR", 1), "s2": (1002, "NEAR", 1), "s3": (1003, "NOT_NEAR", 2), "s4": (1001, "NEAR", 4), "s5": (1002, "NEAR", 1)}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        sid = self.path.split("/")[3]
        if sid not in S: self.send_response(404); self.end_headers(); return
        b = json.dumps(att(sid, *S[sid])).encode()
        self.send_response(200); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(b)
HTTPServer(("127.0.0.1", 8599), H).serve_forever()
