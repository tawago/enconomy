"""Rechecks two facts spec.md cites: what a /fail report looks like to the partner, and the 500 on a very deep create body.

It shows the server follows its rules on signed numbers. It does not show a phone told the truth about the air (CN1).
Scope: sessions with context=None and policy human=none only. Fake clock and FastAPI test client. uvicorn is not run.
Assumptions, by name: honest server code as written, one worker process, no await between load and save.

This lives apart from spec-checks/recheck.py and uses its Walk helper. Run from fv/v1/server/tests, server/ at 9db1490:
  python recheck_m6_fail.py
Each line is  [PASS|FAIL] id: what. Exit code 1 if any line fails.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / "spec-checks"))

import recheck  # noqa: E402
from recheck import Walk, check  # noqa: E402

TEXT = "self_timestamp_mismatch"
SEEN_FIELDS = ("state", "attempt", "t0_ms", "last_failure", "result", "armed", "committed", "submitted", "confirmed")


def started():
    """Both phones armed and past the commit gate. Nobody has committed yet."""
    w = Walk().pair()
    w.arm()
    w.clock.ms = w.t0 + 1200
    return w


def committed():
    w = started()
    w.commit(w.a, "A", 0)
    w.commit(w.b, "B", 0)
    return w


def seen(view):
    return {k: view[k] for k in SEEN_FIELDS}


def fail(w, phone, reason=TEXT, attempt=0):
    return w.post(phone, "/fail", {"attempt": attempt, "reason": reason})


def report_from_fail_looks_like_combine():
    # A is far out of range. B never sends a transcript. B posts /fail. combine never runs.
    w1 = committed()
    r1 = w1.submit(w1.a, w1.b, "A", 0, 1234, delta=5000)
    r2 = fail(w1, w1.b)
    v1 = w1.view(w1.a)
    lf = v1["last_failure"]
    check("M6-leak", "/fail: A out of range, B sends /fail, A's view says by B", r1.status_code == 200 and r2.status_code == 200
          and lf["attempt"] == 0 and lf["reason"] == TEXT and lf["by"] == "B" and v1["attempt"] == 1, lf)
    check("M6-leak", "/fail: combine did not run, B stored no transcript", "transcript_b64" not in w1.doc()["attempts"][0]["per_role"]["B"]
          and w1.doc().get("last_flight_cm") is None)

    # A is in range, B out of range, A first. combine runs inside B's request.
    w2 = committed()
    r3 = w2.submit(w2.a, w2.b, "A", 0, 1234, delta=0)
    r4 = w2.submit(w2.b, w2.a, "B", 0, 0, delta=5000)
    v2 = w2.view(w2.a)
    check("M6-leak", "combine: A in range, B out, A's view says by B", v2["last_failure"]["by"] == "B" and v2["last_failure"]["reason"] == TEXT, v2["last_failure"])
    check("M6-leak", "combine ran here: the stored row holds B's transcript", "transcript_b64" in w2.doc()["attempts"][0]["per_role"]["B"])
    check("M6-leak", "A's own transcript answer was the same in both, attempt 0", r1.json() == r3.json(), r1.json())
    a, b = seen(v1), seen(v2)
    a.pop("t0_ms"), b.pop("t0_ms")
    check("M6-leak", "A's two views are equal, field by field, though A's delta was 5000 in one and 0 in the other", a == b)
    check("M6-leak", "B's transcript answer shows the attempt moved, so B knows combine ran", r4.status_code == 200 and r4.json()["attempt"] == 1, r4.json())


def by_a_from_fail():
    w1 = committed()
    w1.submit(w1.b, w1.a, "B", 0, 1234, delta=5000)
    fail(w1, w1.a)
    v1 = w1.view(w1.b)
    w2 = committed()
    w2.submit(w2.b, w2.a, "B", 0, 1234, delta=0)
    w2.submit(w2.a, w2.b, "A", 0, 0, delta=5000)
    v2 = w2.view(w2.b)
    a, b = seen(v1), seen(v2)
    a.pop("t0_ms"), b.pop("t0_ms")
    check("M6-leak", "by A: from A's /fail and from combine, B's two views are equal", a == b and a["last_failure"]["by"] == "A", a["last_failure"])


def when_a_phone_can_tell():
    # A saw B's flag. B's /fail is then refused, so a later report must come from combine.
    w = committed()
    w.submit(w.b, w.a, "B", 0, 0, delta=5000)
    v = w.view(w.a)
    r = fail(w, w.b)
    check("M6-leak", "A sees submitted B, then B's /fail is 409 already_submitted, no change",
          v["submitted"]["B"] and r.status_code == 409 and r.json()["error"] == "already_submitted" and w.view(w.a)["last_failure"] is None, r.text[:60])
    r = w.submit(w.a, w.b, "A", 0, 1234, delta=0)
    v = w.view(w.a)
    check("M6-leak", "A's own transcript moves the attempt, so A knows combine ran, by B", r.json()["attempt"] == 1 and v["last_failure"]["by"] == "B", r.json())

    # A sent no transcript at all. The report can't come from combine.
    w = started()
    r = fail(w, w.b)
    v = w.view(w.a)
    check("M6-leak", "no commit, no transcript from anyone: /fail still gives the report, by B", r.status_code == 200 and v["last_failure"]["by"] == "B"
          and v["last_failure"]["reason"] == TEXT, v["last_failure"])


def only_combine_gives_impossible_flight():
    for reason in ["impossible_flight", "timeout"]:
        w = committed()
        before = w.doc()
        r = fail(w, w.b, reason)
        check("M6-leak", f"/fail with {reason}: 400 bad_reason, no change", r.status_code == 400 and r.json()["error"] == "bad_reason" and w.doc() == before, r.text[:60])


def deep_create():
    path = "/v1/session"

    def deep(depth):
        return b"[" * depth + b"]" * depth

    w = Walk(raise_500=False)
    count = lambda: w.store._db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]  # noqa: E731
    n = count()
    for depth in [5000, 9000, 9900, 9990, 10000, 10100, 11000, 12000]:
        raw = deep(depth)
        r = w.client.post(path, content=raw, headers=w.a.headers("POST", path, raw))
        print(f"[INFO] E500-create scan: depth {depth}: {r.status_code} {r.text[:50]}, sessions stored {count() - n}", flush=True)
    raw = deep(5000)
    r = w.client.post(path, content=raw, headers=w.a.headers("POST", path, raw))
    check("E500-create", "depth 5000: 400 bad_request, nothing stored", r.status_code == 400 and r.json()["error"] == "bad_request" and count() == n, r.text[:60])
    raw = deep(12000)
    r = w.client.post(path, content=raw, headers=w.a.headers("POST", path, raw))
    check("E500-create", "depth 12000: 500, nothing stored", r.status_code == 500 and count() == n, r.status_code)
    r = w.client.post(path, content=raw, headers={"content-type": "application/json"})
    check("E500-create", "depth 12000, no auth: 401, auth comes first here", r.status_code == 401 and count() == n, r.status_code)
    w = Walk(raise_500=True)
    try:
        r = w.client.post(path, content=raw, headers=w.a.headers("POST", path, raw))
        check("E500-create", "depth 12000: the cause is RecursionError", False, r.status_code)
    except RecursionError:
        check("E500-create", "depth 12000: the cause is RecursionError", True)


if __name__ == "__main__":
    print("M6 /fail report and E500-create. Says the server follows its rules on signed numbers. Says nothing about the air (CN1).", flush=True)
    src = recheck.SERVER / "pop"
    for name in ["sessions.py", "verdict.py", "main.py"]:
        print(f"[INFO] {name} sha256 {hashlib.sha256((src / name).read_bytes()).hexdigest()}", flush=True)
    report_from_fail_looks_like_combine()
    by_a_from_fail()
    when_a_phone_can_tell()
    only_combine_gives_impossible_flight()
    deep_create()
    print(f"done, {recheck.fails} failed", flush=True)
    sys.exit(1 if recheck.fails else 0)
