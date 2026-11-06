"""Records to MeetResolver txs: a fake chain, a fake core for the bundle, the real routes and worker."""
import hashlib
import json
import urllib.error
import urllib.request
from io import BytesIO

from fastapi.testclient import TestClient

from backend.main import create_app
from bridge import bridge as B
from tests.helpers import VECTOR, FakeChain, Phone, keccak256, near_record, wait_for

SID = "ab" * 16
BUNDLE_URL = f"http://core.invalid/v1/session/{SID}/zk/bundle"
PROOF = {"A": b"\x0a" * 64, "B": b"\x0b" * 64}
INPUTS = {"A": ["0x" + "01" * 32, "0x" + "02" * 32], "B": ["0x" + "03" * 32, "0x" + "04" * 32]}

# From `cast keccak`, run by hand on the old bridge.py's inputs. Values already on Sepolia follow these formulas.
VEC_MID = "0xe0e54e825ad3653234553f3e9baf16f259b7e2fa27bbb90ed268d452faf126d6"
VEC_EV = "0x8c599e25070d51dc6b3250709f29f05be7a6b54c595db33192b2548f9c6268d0"
VEC_TB = 497222
ALICE = "0x9c0257114eb9399a2985f8e75dad7600c5d89fe3824ffa99ec1c3eb8bf3b0501"
BOB = "0x38e47a7b719dce63662aeaf43440326f551b8a7ee198cee35cb5d517f2d296a2"


def zk_block(status="verified", shas=None):
    def ent(role):
        return {"status": "verified", "attempt": 0, "proof_sha256": (shas or {}).get(role, hashlib.sha256(PROOF[role]).hexdigest()),
                "public_inputs": INPUTS[role]}
    return {"status": status, "A": ent("A"), "B": ent("B"), "pair": None}


def bundle(**over):
    return {"format": "pop-zk-bundle-1", "session_id": SID,
            "proofs": {r: {"proof": "0x" + PROOF[r].hex(), "public_inputs": INPUTS[r]} for r in "AB"}, **over}


def add_name(client, device_id, label, chain, status="registered"):
    client.app.state.store.db.execute("INSERT INTO ens_names(device_id, label, claimed_at, status) VALUES (?, ?, 't', ?)",
                                      (device_id, label, status))
    chain.onchain.add(label)


def named_pair(client, clock, chain):
    a, b = Phone(client, clock), Phone(client, clock)
    add_name(client, a.device_id, "alice", chain)
    add_name(client, b.device_id, "bobby", chain)
    return a, b


def row(client, sid=SID):
    return client.app.state.store.get_record(sid)


def post(client, rec):
    r = client.post("/v1/presence", json=rec)
    assert r.status_code == 200, r.text
    return r


def settle(client):
    """One whole pass, here on the test's thread. The worker thread ends first, so from now on nothing races the test."""
    w = client.app.state.worker
    w.stop()
    w._stop = False
    w.run_pass()


def txs(chain, what):
    return [c for c in chain.calls if c[0] == what]


def recorded(client, clock, chain, zk=None):
    a, b = named_pair(client, clock, chain)
    post(client, near_record(a, b, SID, zk=zk))
    settle(client)
    assert row(client)["status"] == "recorded"
    return a, b


def test_keccak_helper_and_golden_formulas():
    """meetingId, evidence and timeBucket as the old bridge computed them, against values from real cast."""
    body, ch = VECTOR["record"]["body"], FakeChain()
    assert "0x" + keccak256(b"alice").hex() == ALICE and "0x" + keccak256(b"bob").hex() == BOB
    assert B.TAG_HEX == b"enconomy/meet/v1".hex()
    assert B.meeting_id(ch, body["session_id"]) == VEC_MID
    assert B.evidence(ch, body["transcripts"]["A"]["sha256"], body["transcripts"]["B"]["sha256"]) == VEC_EV
    assert B.time_bucket(body["t0_ms"]) == VEC_TB


def test_vector_record_drives_a_record_end_to_end(client, chain):
    devs = VECTOR["record"]["body"]["devices"]
    add_name(client, devs["A"]["device_id"], "alice", chain)
    add_name(client, devs["B"]["device_id"], "bob", chain)
    post(client, VECTOR["record"])
    wait_for(lambda: txs(chain, "record"))
    assert txs(chain, "record") == [("record", (VEC_MID, ALICE, BOB, VEC_TB, VEC_EV))]
    wait_for(lambda: row(client, VECTOR["record"]["body"]["session_id"])["status"] == "recorded")
    r = row(client, VECTOR["record"]["body"]["session_id"])
    assert r["meeting_id"] == VEC_MID and json.loads(r["labels"]) == ["alice", "bob"] and r["tx"].startswith("0x")
    assert r["first_time"] == 1 and r["time_bucket"] == VEC_TB and r["zk_done"] == 0


def test_near_drives_one_record_and_redelivery_no_second_tx(client, clock, chain):
    a, b = named_pair(client, clock, chain)
    rec = near_record(a, b, SID)
    post(client, rec)
    wait_for(lambda: txs(chain, "record"))
    assert post(client, rec).json()["status"] == "unchanged"
    settle(client)
    assert len(txs(chain, "record")) == 1


def test_non_near_no_tx(client, clock, chain):
    a, b = named_pair(client, clock, chain)
    post(client, near_record(a, b, SID, verdict="FAR"))
    wait_for(lambda: (row(client) or {}).get("status") == "ignored")
    assert not chain.calls and row(client)["reason"] == "verdict FAR"
    assert client.app.state.store.undone_records() == []


def test_unmapped_skipped_then_recorded_after_claim(client, clock, chain):
    a, b = Phone(client, clock), Phone(client, clock)
    add_name(client, b.device_id, "bobby", chain)
    post(client, near_record(a, b, SID))
    wait_for(lambda: (row(client) or {}).get("status") == "skipped")
    assert row(client)["reason"] == f"unmapped device A={a.device_id[:8]}" and not chain.calls
    assert a.claim("alice").status_code == 200    # register, touch, then the same pass finds the name
    wait_for(lambda: row(client)["status"] == "recorded")
    assert len(txs(chain, "record")) == 1


def test_other_skip_reasons(client, clock, chain):
    a, b = Phone(client, clock), Phone(client, clock)
    add_name(client, a.device_id, "alice", chain)
    post(client, near_record(a, a, SID))
    wait_for(lambda: (row(client) or {}).get("status") == "skipped")
    assert row(client)["reason"] == "same label alice"

    add_name(client, b.device_id, "BAD_LABEL", chain)
    sid2 = "cd" * 16
    post(client, near_record(a, b, sid2))
    wait_for(lambda: (row(client, sid2) or {}).get("status") == "skipped")
    assert row(client, sid2)["reason"] == "bad label 'BAD_LABEL'"

    c = Phone(client, clock)
    add_name(client, c.device_id, "carol", chain)
    chain.onchain.discard("carol")
    sid3 = "ef" * 16
    post(client, near_record(a, c, sid3))
    wait_for(lambda: (row(client, sid3) or {}).get("status") == "skipped")
    assert row(client, sid3)["reason"] == "carol.enconomy.eth not registered"
    assert not chain.calls


def test_duplicate_meeting_counts_as_done(client, clock, chain):
    mid = B.meeting_id(chain, SID)
    chain.meetings[mid] = {"exists": True, "zk": False, "voided": False}
    a, b = named_pair(client, clock, chain)
    post(client, near_record(a, b, SID))
    wait_for(lambda: (row(client) or {}).get("status") == "duplicate")
    assert not txs(chain, "record") and row(client)["meeting_id"] == mid


def test_duplicate_found_by_the_preflight_or_the_send(client, clock, chain):
    a, b = named_pair(client, clock, chain)
    chain.would_revert = "DuplicateMeeting"
    post(client, near_record(a, b, SID))
    wait_for(lambda: (row(client) or {}).get("status") == "duplicate")
    chain.would_revert, chain.send_revert = None, "DuplicateMeeting"
    post(client, near_record(a, b, "cd" * 16))
    wait_for(lambda: (row(client, "cd" * 16) or {}).get("status") == "duplicate")
    assert not txs(chain, "record")


def test_other_revert_is_a_skip_with_its_name(client, clock, chain):
    a, b = named_pair(client, clock, chain)
    chain.would_revert = "SameName"
    post(client, near_record(a, b, SID))
    wait_for(lambda: (row(client) or {}).get("status") == "skipped")
    assert row(client)["reason"] == "record would revert: SameName" and not chain.calls


def test_chain_error_stays_undone_and_redelivery_retries(client, clock, chain):
    a, b = named_pair(client, clock, chain)
    rec = near_record(a, b, SID)
    chain.fail = "rpc down"
    post(client, rec)
    wait_for(lambda: (row(client) or {}).get("reason") == "rpc down")
    assert row(client)["status"] is None
    chain.fail = None
    assert post(client, rec).json()["status"] == "unchanged"
    wait_for(lambda: row(client)["status"] == "recorded")


def test_late_zk_record_verifies_and_marks(client, clock, chain, http, settings):
    a, b = recorded(client, clock, chain)
    assert not http.calls      # no zk yet: no fetch
    http.routes[BUNDLE_URL] = (200, bundle())
    assert post(client, near_record(a, b, SID, zk=zk_block())).json()["status"] == "updated"
    settle(client)
    verifier, log = "0x" + "33" * 20, "0x" + "44" * 20
    assert txs(chain, "verify") == [
        ("verify", (verifier, log, "0x" + PROOF[r].hex(), "[" + ",".join(INPUTS[r]) + "]")) for r in "AB"]
    assert txs(chain, "mark") == [("mark", row(client)["meeting_id"])]
    r = row(client)
    assert r["zk_done"] == 1 and r["zk_tx"] and set(json.loads(r["verify_tx"])) == {"A", "B"}
    assert client.app.state.store.undone_records() == []
    # and again, nothing more
    n = len(chain.calls)
    post(client, near_record(a, b, SID, zk=zk_block()))
    settle(client)
    assert len(chain.calls) == n


def test_zk_arriving_with_the_first_record(client, clock, chain, http):
    http.routes[BUNDLE_URL] = (200, bundle())
    recorded(client, clock, chain, zk=zk_block())
    assert len(txs(chain, "verify")) == 2 and len(txs(chain, "mark")) == 1
    assert [c[0] for c in chain.calls if c[0] in ("record", "verify", "mark")] == ["record", "verify", "verify", "mark"]


def test_bad_proof_hash_refused_then_good_bundle_goes(client, clock, chain, http):
    a, b = recorded(client, clock, chain)
    bad = bundle()
    bad["proofs"]["B"]["proof"] = "0x" + (b"\xff" * 64).hex()
    http.routes[BUNDLE_URL] = (200, bad)
    post(client, near_record(a, b, SID, zk=zk_block()))
    settle(client)
    assert not txs(chain, "verify") and not txs(chain, "mark")   # B is bad: A isn't sent either
    r = row(client)
    assert r["zk_done"] == 0 and r["reason"] == "zk refused: B: proof sha256 is not the signed one"
    http.routes[BUNDLE_URL] = (200, bundle())
    settle(client)
    assert len(txs(chain, "verify")) == 2 and len(txs(chain, "mark")) == 1 and row(client)["reason"] is None


def test_bundle_that_differs_from_the_signed_record_refused(client, clock, chain, http):
    a, b = recorded(client, clock, chain)
    post(client, near_record(a, b, SID, zk=zk_block()))
    swapped = bundle()
    swapped["proofs"]["A"]["public_inputs"] = INPUTS["B"]
    for bad, why in ((swapped, "A: public inputs"), (bundle(session_id="cd" * 16), "another session"),
                     ({"session_id": SID}, "another session")):
        http.routes[BUNDLE_URL] = (200, bad)
        settle(client)
        assert why in row(client)["reason"]
    assert not txs(chain, "verify") and not txs(chain, "mark")


def test_bundle_404_skips_verify_and_still_marks(client, clock, chain, http, settings):
    a, b = recorded(client, clock, chain)
    post(client, near_record(a, b, SID, zk=zk_block()))
    settle(client)
    assert http.calls == [BUNDLE_URL] and not txs(chain, "verify") and len(txs(chain, "mark")) == 1
    assert row(client)["zk_done"] == 1 and json.loads(row(client)["verify_tx"]) == {"A": None, "B": None}
    log = settings.log.read_text()
    assert "onchain verify skipped" in log and SID not in log


def test_core_down_marks_nothing_and_retries(client, clock, chain, http):
    a, b = recorded(client, clock, chain)
    post(client, near_record(a, b, SID, zk=zk_block()))
    for bad in (OSError("refused"), (503, None)):
        http.routes[BUNDLE_URL] = bad
        settle(client)
        assert not txs(chain, "mark") and row(client)["zk_done"] == 0 and row(client)["reason"]
    http.routes[BUNDLE_URL] = (200, bundle())
    settle(client)
    assert len(txs(chain, "mark")) == 1


def test_a_failed_verify_send_does_not_resend_the_first_proof(client, clock, chain, http):
    a, b = recorded(client, clock, chain)
    http.routes[BUNDLE_URL] = (200, bundle())
    post(client, near_record(a, b, SID, zk=zk_block()))
    send, seen = chain.verify_send, []

    def once_ok(verifier, log, proof, inputs):
        seen.append(proof)
        if len(seen) == 2:
            raise RuntimeError("rpc down")
        return send(verifier, log, proof, inputs)
    chain.verify_send = once_ok
    settle(client)
    assert list(json.loads(row(client)["verify_tx"])) == ["A"] and not txs(chain, "mark")
    settle(client)
    assert seen == ["0x" + PROOF["A"].hex(), "0x" + PROOF["B"].hex(), "0x" + PROOF["B"].hex()]
    assert len(txs(chain, "mark")) == 1


def test_verifier_says_no_sends_nothing_and_marks_as_before(client, clock, chain, http):
    """The core checked these proofs, and the old bridge marked in this case too. Only the manual zk-verify stops."""
    a, b = recorded(client, clock, chain)
    http.routes[BUNDLE_URL] = (200, bundle())
    chain.verify_result = "false"
    post(client, near_record(a, b, SID, zk=zk_block()))
    settle(client)
    assert not txs(chain, "verify") and len(txs(chain, "mark")) == 1


def test_void_or_already_zk_meeting_needs_no_tx(client, clock, chain, http):
    a, b = recorded(client, clock, chain)
    chain.meetings[row(client)["meeting_id"]]["voided"] = True
    post(client, near_record(a, b, SID, zk=zk_block()))
    settle(client)
    assert not http.calls and not txs(chain, "mark") and row(client)["zk_done"] == 1


def test_no_verifier_configured_only_marks(settings, clock, chain, http):
    settings.zk_deployments = settings.db.parent / "missing.json"
    with TestClient(create_app(settings, chain, clock, http)) as client:
        a, b = recorded(client, clock, chain)
        post(client, near_record(a, b, SID, zk=zk_block()))
        settle(client)
        assert not http.calls and not txs(chain, "verify") and len(txs(chain, "mark")) == 1


def test_status_survives_a_restart(settings, clock, chain, http):
    """Recorded stays recorded: nothing in a new process sends it twice."""
    with TestClient(create_app(settings, chain, clock, http)) as client:
        recorded(client, clock, chain)
    n = len(txs(chain, "record"))
    with TestClient(create_app(settings, chain, clock, http)) as client:
        settle(client)
        assert row(client)["status"] == "recorded" and len(txs(chain, "record")) == n


def test_words_are_the_file_format():
    assert B.words(INPUTS["A"]) == b"\x01" * 32 + b"\x02" * 32


def test_cfg_defaults_read_the_examples_own_deployments(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_CONFIG", str(tmp_path / "none.json"))
    c = B.Cfg(log=tmp_path / "l")
    assert c.resolver == json.loads((B.HERE.parent / "contracts/deployments/sepolia.json").read_text())["meetResolver"]
    assert c.phone_verifier and c.verify_log
    assert B.HERE.parent in c["deployments"].parents and B.HERE.parent in c["db"].parents


def test_http_get_json(monkeypatch):
    def not_found(url, timeout):
        raise urllib.error.HTTPError(url, 404, "nope", {}, BytesIO(b"{}"))
    monkeypatch.setattr(urllib.request, "urlopen", not_found)
    assert B.http_get_json("http://core.invalid/x") == (404, None)

    class Reply(BytesIO):
        status = 200
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: Reply(b'{"a":1}'))
    assert B.http_get_json("http://core.invalid/x") == (200, {"a": 1})


# ------------------------------------------------------------------ the CLI

def cli_bridge(settings, chain, tmp_path, monkeypatch):
    monkeypatch.setenv("ENS_DEPLOYMENTS", str(settings.deployments))
    monkeypatch.setenv("ENS_ZK_DEPLOYMENTS", str(settings.zk_deployments))
    monkeypatch.setenv("BRIDGE_LOG", str(settings.log))
    monkeypatch.setenv("ENS_DB", str(settings.db))
    monkeypatch.setenv("BRIDGE_CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setattr(B, "Chain", lambda *a: chain)
    monkeypatch.setattr(B.shutil, "which", lambda _: "/bin/cast")


def test_cli_record_with_a_sid_uses_the_stored_record(settings, clock, chain, http, tmp_path, monkeypatch, capsys):
    cli_bridge(settings, chain, tmp_path, monkeypatch)
    vec = VECTOR["record"]
    sid = vec["body"]["session_id"]
    with TestClient(create_app(settings, chain, clock, http)) as client:
        post(client, vec)
    assert B.main(["record", "alice", "bob", sid]) == 0
    assert txs(chain, "record") == [("record", (VEC_MID, ALICE, BOB, VEC_TB, VEC_EV))]
    assert VEC_MID in capsys.readouterr().out


def test_cli_record_without_a_stored_record_is_a_rehearsal(settings, chain, tmp_path, monkeypatch):
    cli_bridge(settings, chain, tmp_path, monkeypatch)
    assert B.main(["record", "alice", "bob", SID]) == 0
    assert txs(chain, "record")[0][1][0] == B.meeting_id(chain, SID)


def test_cli_run_and_import_names_need_no_chain(tmp_path, monkeypatch, capsys):
    assert B.main(["run"]) == 0
    assert "uvicorn" in capsys.readouterr().out
    called = []
    monkeypatch.setattr(B.import_names, "main", lambda a: called.append(a) or 0)
    assert B.main(["import-names", "old", "new"]) == 0 and called == [["old", "new"]]
