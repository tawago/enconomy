"""The queue, with relay.mjs faked: nothing here touches node, a key or a chain."""
from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from tests.helpers import NOW_MS, SID, near_record, tx
from tests.test_presence import register, sign_both


class FakeRunner:
    def __init__(self, *statuses):
        self.statuses = list(statuses) or ["success"]
        self.calls, self.jobs = [], []
        self.called = threading.Event()

    def __call__(self, cmd, env, cwd):
        self.calls.append((cmd, env, cwd))
        self.jobs.append(json.loads(open(cmd[-1]).read()))
        self.called.set()
        status = self.statuses.pop(0)
        return f"log noise\n{json.dumps({'sid': SID, 'status': status, 'tx_hash': '0xabc'})}\n"


def app(settings, runner, wake=lambda: None):
    """An injected wake leaves the thread idle, so a test drives run_pass itself."""
    return TestClient(create_app(settings, now_ms=lambda: NOW_MS, runner=runner, wake=wake))


def deliver(c, phones):
    a, b = phones
    h = register(c)
    sign_both(c, h, phones)
    rec = near_record(a, b, h)
    assert c.post(f"/v1/spends/{h}/presence", json=rec).status_code == 200
    return h, rec


def test_near_runs_relay_once_through_the_real_thread(settings, phones):
    a, b = phones
    runner = FakeRunner()
    with TestClient(create_app(settings, now_ms=lambda: NOW_MS, runner=runner)) as c:
        h, _ = deliver(c, phones)
        att = c.app.state.store.get_attestation(SID)["att"]
        sigs = {"A": c.app.state.store.owner_sig(h, a.pub.hex()), "B": c.app.state.store.owner_sig(h, b.pub.hex())}
        assert runner.called.wait(5)
        for _ in range(100):
            relay = c.get(f"/v1/spends/{h}/relay").json()
            if relay["status"] != "pending":
                break
            time.sleep(0.05)
    assert relay == {"status": "success", "session_id": SID,
                     "result": {"sid": SID, "status": "success", "tx_hash": "0xabc"}}
    assert len(runner.calls) == 1

    cmd, env, cwd = runner.calls[0]
    assert cmd[:3] == ["node", "relay.mjs", "--fixture"] and (cwd / "relay.mjs").exists()
    assert env["OUT_DIR"] == str(settings.db.resolve().parent / "relay-out")
    assert env["POP_SERVER_URL"] == "http://core.invalid" and env["RPC"] == "http://no"
    assert env["CHAIN_ID"] == "11155111" and env["RELAYER_KEY_FILE"] == str(settings.relayer_key_file)

    # every field relay.mjs reads, roles from the record
    assert runner.jobs[0] == {
        "session_id": SID, "state": "done", "verdict": "NEAR", "not_before": (1_790_000_003_000 // 1000) - 3,
        "context": {"chain_id": 11155111, "consumer": "0x" + "5afe" * 10, "ctx_hash": h, "safe_tx": tx()},
        "att": att,
        "safe": {"owner_sigs": sigs}}
    assert set(att) >= {"v", "pair_tag", "dev_a", "dev_b", "expiry", "digest", "r", "s", "tail_hex"}
    assert all(s.startswith("0x") for s in sigs.values())


def test_refused_record_never_reaches_the_runner(settings, phones):
    a, b = phones
    runner = FakeRunner()
    with app(settings, runner) as c:
        h = register(c)
        sign_both(c, h, phones)
        assert c.post(f"/v1/spends/{h}/presence", json=near_record(a, b, h, verdict="FAR")).status_code == 403
        c.app.state.worker.run_pass()
    assert runner.calls == []


def test_redelivery_retries_a_failed_job_and_not_a_sent_one(settings, phones):
    runner = FakeRunner("error", "success")
    with app(settings, runner) as c:
        h, rec = deliver(c, phones)
        c.app.state.worker.run_pass()
        assert c.get(f"/v1/spends/{h}/relay").json()["status"] == "error"
        c.app.state.worker.run_pass()               # a pass alone doesn't retry
        assert len(runner.calls) == 1

        assert c.post(f"/v1/spends/{h}/presence", json=rec).json()["relay"] == "pending"
        c.app.state.worker.run_pass()
        assert c.get(f"/v1/spends/{h}/relay").json()["status"] == "success"

        assert c.post(f"/v1/spends/{h}/presence", json=rec).json()["relay"] == "success"
        c.app.state.worker.run_pass()
    assert len(runner.calls) == 2


def test_startup_runs_what_a_crash_left_pending(settings, phones):
    with app(settings, FakeRunner()) as c:
        h, _ = deliver(c, phones)   # queued, the idle thread never ran it
    runner = FakeRunner()
    with TestClient(create_app(settings, now_ms=lambda: NOW_MS, runner=runner)):
        assert runner.called.wait(5)
    assert runner.jobs[0]["context"]["ctx_hash"] == h


@pytest.mark.parametrize("bad", [lambda *_: "not json\n", lambda *_: (_ for _ in ()).throw(TimeoutError("slow"))])
def test_a_bad_run_is_an_error_status(settings, phones, bad):
    with app(settings, bad) as c:
        h, _ = deliver(c, phones)
        c.app.state.worker.run_pass()
        assert c.get(f"/v1/spends/{h}/relay").json()["status"] == "error"
