"""On chain at the claim: a claim wakes one worker thread, with no poll anywhere."""
import time

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.store import Store
from tests.helpers import Phone, settled, wait_for


def test_claim_reaches_register_and_touch_without_a_poll(client, clock, chain):
    time.sleep(0.05)   # the startup pass is done, the worker sleeps
    # a row nobody woke the worker for stays put: there is no timer that would have sent it
    client.app.state.store.db.execute("INSERT INTO ens_names(device_id, label, claimed_at) VALUES ('d', 'quiet', 't')")
    time.sleep(0.2)
    assert not chain.calls
    p = Phone(client, clock)
    r = p.claim("carol")
    assert r.json()["status"] == "pending" and r.json()["tx"] is None
    wait_for(lambda: p.read().json()["status"] == "registered")
    assert ("register", "carol") in chain.calls and ("touch", "carol") in chain.calls
    assert chain.calls.index(("register", "carol")) < chain.calls.index(("touch", "carol"))
    assert p.read().json()["tx"].startswith("0x")


def test_many_claims_go_serially(client, clock, chain):
    phones = [Phone(client, clock) for _ in range(5)]
    for i, p in enumerate(phones):
        assert p.claim(f"phone-{i}").status_code == 200
    wait_for(lambda: settled(client.app) and len(chain.calls) == 10)
    assert not chain.overlapped


def test_no_daily_cap(client, clock, chain):
    """Many claims in one instant all go out."""
    n = 25
    for i in range(n):
        assert Phone(client, clock).claim(f"name-{i}").status_code == 200
    wait_for(lambda: settled(client.app), timeout=10)
    assert sum(1 for c in chain.calls if c[0] == "register") == n


def test_pending_rows_retried_at_startup(settings, chain, clock):
    s = Store(settings.db)
    s.db.execute("INSERT INTO ens_names(device_id, label, claimed_at) VALUES ('d1', 'crashed', 't')")
    s.close()
    with TestClient(create_app(settings, chain, clock)) as c:
        wait_for(lambda: settled(c.app))
        assert ("register", "crashed") in chain.calls
        assert c.app.state.store.get_name("d1")["status"] == "registered"


def test_label_already_onchain_counts_as_done(client, clock, chain):
    """A crash after the tx, or a hand registered name: no second tx. So a hand registered label not in the table
    goes to whoever claims it first (README)."""
    chain.onchain.add("carol")
    p = Phone(client, clock)
    assert p.claim("carol").status_code == 200
    wait_for(lambda: p.read().json()["status"] == "registered")
    assert not chain.calls and p.read().json()["tx"] is None


def test_chain_failure_marks_failed_and_worker_lives(client, clock, chain):
    p, q = Phone(client, clock), Phone(client, clock)
    chain.fail = "rpc down"
    p.claim("carol")
    wait_for(lambda: p.read().json()["status"] == "failed")
    assert client.app.state.store.get_name(p.device_id)["error"] == "rpc down"
    chain.fail = None
    q.claim("erin")
    wait_for(lambda: q.read().json()["status"] == "registered")
