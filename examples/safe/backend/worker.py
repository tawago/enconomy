"""One thread does everything onchain, in the backend process, so the relay key sends serially.

It sleeps until woken: at startup (a crash can leave pending rows) and on each presence record. No poll.
A pass hands each pending job to relay.mjs and stores the status line it prints.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path

from backend.config import Settings
from backend.core import ROLES
from backend.store import Store

log = logging.getLogger("safe")

RELAY_TIMEOUT_S = 180   # relay.mjs waits up to 60 s for a receipt. Killed after sending, a rerun only reads the receipt


def run_node(cmd: list[str], env: dict, cwd: Path) -> str:
    """Exit codes don't matter: relay.mjs reports every outcome on stdout."""
    return subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=RELAY_TIMEOUT_S).stdout


def status_line(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("status"), str):
            return obj
    return {"status": "error", "error": "no_status_line"}


class Worker:
    def __init__(self, store: Store, settings: Settings, runner=run_node):
        self.store, self.settings, self.runner = store, settings, runner
        self.data = settings.db.resolve().parent
        self._wake = threading.Event()
        self._stop = False
        self._thread = None

    def start(self) -> None:
        self._stop = False
        self._wake.set()
        self._thread = threading.Thread(target=self._run, name="safe-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()   # before the pass, so a wake during it isn't lost
            if self._stop:
                return
            try:
                self.run_pass()
            except Exception:  # noqa: BLE001 - the thread must outlive one bad pass
                log.exception("worker pass failed")

    def run_pass(self) -> None:
        for job in self.store.pending_jobs():
            if self._stop:
                return
            sid = job["session_id"]
            try:
                result = status_line(self.runner(*self.command(self.write_job(job))))
            except Exception as e:  # noqa: BLE001 - this job failed, a redelivery retries; others still go
                result = {"status": "error", "error": str(e)[:200]}
            self.store.set_job(sid, result["status"], json.dumps(result))
            log.info("relay %s -> %s", sid, result["status"])

    def job_body(self, job: dict) -> dict:
        ctx_hash = job["ctx_hash"]
        stored = self.store.get_attestation(job["session_id"])
        body, spend = stored["body"], self.store.get_spend(ctx_hash)
        sigs = {r: self.store.owner_sig(ctx_hash, bytes.fromhex(body["devices"][r]["pubkey"]).hex()) for r in ROLES}
        return {"session_id": job["session_id"], "state": "done", "verdict": body["verdict"],
                "context": {"chain_id": spend["chain_id"], "consumer": spend["safe"], "ctx_hash": ctx_hash,
                            "safe_tx": spend["safe_tx"]},
                "not_before": body["not_before"], "att": stored["att"], "safe": {"owner_sigs": sigs}}

    def write_job(self, job: dict) -> Path:
        path = self.data / "relay-jobs" / f"{job['session_id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.job_body(job)))
        return path

    def command(self, job_file: Path) -> tuple[list[str], dict, Path]:
        s = self.settings
        env = {**os.environ, "OUT_DIR": str(self.data / "relay-out"), "RPC": s.rpc, "POP_SERVER_URL": s.core_url,
               "CHAIN_ID": str(s.chain_id)}
        if s.relayer_key_file:
            env["RELAYER_KEY_FILE"] = str(s.relayer_key_file)
        return ["node", "relay.mjs", "--fixture", str(job_file)], env, s.relayer_dir
