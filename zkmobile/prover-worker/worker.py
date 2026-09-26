#!/usr/bin/env python3
"""Remote zkprove worker for the PoP server's delegated proofs (python3 stdlib only).

POST /prove  Authorization: Bearer <secret>
  body (JSON, optionally Content-Encoding: gzip, <= 5 MB either way):
    {"circuit": "oaN_s48", "inputs": <Prover.toml text | Noir JSON input map>}
  200 {"proof_b64", "public_inputs_b64", "ms"}
  401 bad / missing secret, 413 body too big, 400 bad request, 422 {"error": "witness_failed", "detail"},
  504 prove timed out, 500 anything else.
GET /health -> {"ok": true}

One prove at a time (a lock is the queue); each prove gets 120 s. Inputs live only in a 0700 temp dir that is
removed right after. Listens on 127.0.0.1 only; cloudflared publishes it.

env: WORKER_SECRET (required), ZKPROVE (/opt/zk/bin/zkprove), ZK_ART (/opt/zk/art: oaN_s48.json, oaN_s48.vk,
bn254_g1_2p20.dat), WORKER_PORT (8090), PROVE_TIMEOUT_S (120), HARDWARE_CONCURRENCY (bb threads, passed through).
"""
import base64
import gzip
import hmac
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SECRET = os.environ["WORKER_SECRET"].strip().encode()
ZKPROVE = os.environ.get("ZKPROVE", "/opt/zk/bin/zkprove")
ART = Path(os.environ.get("ZK_ART", "/opt/zk/art"))
PORT = int(os.environ.get("WORKER_PORT", "8090"))
TIMEOUT_S = float(os.environ.get("PROVE_TIMEOUT_S", "120"))
MAX_BODY = 5 << 20
CIRCUITS = {"oaN_s48"}
ONE = threading.Lock()


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def prove(circuit: str, inputs: str) -> tuple[int, dict]:
    art, vk, crs = ART / f"{circuit}.json", ART / f"{circuit}.vk", ART / "bn254_g1_2p20.dat"
    t0 = time.monotonic()
    with ONE:
        waited = time.monotonic() - t0
        d = tempfile.mkdtemp(prefix="zkw-")
        try:
            os.chmod(d, 0o700)
            inp, out = Path(d) / "inputs", Path(d) / "out"
            inp.write_text(inputs)
            t = time.monotonic()
            try:
                r = subprocess.run([ZKPROVE, "full", str(art), str(inp), str(crs), str(vk), str(out)],
                                   capture_output=True, text=True, timeout=TIMEOUT_S)
            except subprocess.TimeoutExpired:
                log(f"prove timeout after {TIMEOUT_S:.0f} s")
                return 504, {"error": "timeout"}
            ms = int((time.monotonic() - t) * 1000)
            if r.returncode == 0 and (out / "proof").is_file():
                res = {"proof_b64": base64.b64encode((out / "proof").read_bytes()).decode(),
                       "public_inputs_b64": base64.b64encode((out / "public_inputs").read_bytes()).decode(),
                       "ms": ms}
                rl = [l for l in r.stdout.splitlines() if l.startswith("RESULT")]
                log(f"prove ok {ms} ms (queued {waited * 1000:.0f} ms) {rl[-1] if rl else ''}")
                return 200, res
        finally:
            shutil.rmtree(d, ignore_errors=True)
    err = (r.stderr + r.stdout).strip()
    m = re.search(r"(witness solve.*|acvm:.*|inputs:.*)", err)
    if m:
        log(f"witness_failed: {m.group(1)[:200]}")
        return 422, {"error": "witness_failed", "detail": m.group(1)[:200]}
    log(f"zkprove rc={r.returncode}: {err[-300:]}")
    return 500, {"error": "prover_failed", "detail": f"rc={r.returncode}"}


class H(BaseHTTPRequestHandler):
    server_version = "zkw/1"
    sys_version = ""

    def log_message(self, fmt, *args):  # quiet default access log (no bodies / headers are logged anyway)
        pass

    def send(self, code: int, obj: dict) -> None:
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health":
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/prove":
            return self.send(404, {"error": "not_found"})
        auth = self.headers.get("Authorization", "")
        if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip().encode(), SECRET)):
            self.close_connection = True
            return self.send(401, {"error": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            n = -1
        if n < 0:
            self.close_connection = True
            return self.send(411, {"error": "length_required"})
        if n > MAX_BODY:
            self.close_connection = True
            return self.send(413, {"error": "too_large"})
        raw = self.rfile.read(n)
        try:
            if self.headers.get("Content-Encoding", "").lower() == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as g:
                    raw = g.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    return self.send(413, {"error": "too_large"})
            req = json.loads(raw)
            circuit, inputs = req["circuit"], req["inputs"]
            if circuit not in CIRCUITS:
                return self.send(400, {"error": "circuit_unknown"})
            if isinstance(inputs, dict):
                inputs = json.dumps(inputs)
            if not isinstance(inputs, str):
                raise ValueError("inputs")
        except Exception:
            return self.send(400, {"error": "bad_request"})
        code, obj = prove(circuit, inputs)
        self.send(code, obj)


if __name__ == "__main__":
    s = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    s.daemon_threads = True
    log(f"zk worker on 127.0.0.1:{PORT}, zkprove={ZKPROVE}, art={ART}, timeout={TIMEOUT_S:.0f}s, "
        f"threads={os.environ.get('HARDWARE_CONCURRENCY', 'all')}")
    s.serve_forever()
