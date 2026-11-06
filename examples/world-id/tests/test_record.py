"""The record intake and the nullifier import. World ID runs through FakeWorld, the record is signed with the vector's
throwaway key."""
import base64
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from backend.import_nullifiers import import_nullifiers
from backend.main import why_not_met
from tests.helpers import NONCE, SID, Phone, fake_nullifier, make_body, sign_record


def verify_both(a, b):
    for p in (a, b):
        assert p.start().status_code == 200
        assert p.until("verified").json()["status"] == "verified"


def deliver(client, signed):
    return client.post("/v1/record", json=signed)


# -- happy path

def test_verified_humans_and_near_met(client, phones):
    a, b = phones
    verify_both(a, b)
    r = deliver(client, sign_record(make_body(a, b)))
    assert r.status_code == 200, r.text
    assert r.json() == {"met": True, "reason": None, "session_id": SID, "session_nonce": NONCE,
                        "finished_at": "2026-09-21T14:13:24.500+00:00", "flight_cm": "30.37",
                        "trust_tier": {"A": "tee", "B": "tee"}}
    assert "nullifier" not in r.text
    assert client.app.state.store.get_meeting(NONCE) == r.json()
    # either phone, again: the same answer
    assert deliver(client, sign_record(make_body(a, b))).json() == r.json()


def test_record_before_world_id_gets_the_answer_on_retry(client, phones):
    a, b = phones
    signed = sign_record(make_body(a, b))
    assert deliver(client, signed).json()["reason"] == "no_world_id"
    verify_both(a, b)
    assert deliver(client, signed).json()["met"] is True


# -- check 4: the core's signature, and the verdict

def test_forged_or_altered_record_refused(client, phones):
    a, b = phones
    verify_both(a, b)
    body = make_body(a, b)
    forged = sign_record(body, key=ec.generate_private_key(ec.SECP256R1()))
    altered = sign_record(body) | {"body": body | {"flight_cm": "1.00"}}
    no_sig = {"body": body}
    bad_b64 = sign_record(body) | {"sig_b64": base64.b64encode(b"x" * 64).decode()}
    for signed in (forged, altered, no_sig, bad_b64):
        r = deliver(client, signed)
        assert r.status_code == 401 and r.json()["error"] == "bad_record_signature", r.text
    assert client.app.state.store.get_meeting(NONCE) is None


def test_far_is_not_met(client, phones):
    a, b = phones
    verify_both(a, b)
    r = deliver(client, sign_record(make_body(a, b, verdict="FAR")))
    assert r.status_code == 200 and r.json()["met"] is False and r.json()["reason"] == "not_near"


def test_signed_but_malformed_record(client, phones):
    a, b = phones
    r = deliver(client, sign_record(make_body(a, b, nonce="short")))
    assert r.status_code == 400 and r.json()["error"] == "bad_record"
    body = make_body(a, b)
    del body["transcripts"]["B"]
    r = deliver(client, sign_record(body))
    assert r.status_code == 400 and r.json()["error"] == "bad_record"


def test_far_with_one_device_answers(client, phones):
    a, b = phones
    body = make_body(a, b, verdict="FAR")
    del body["devices"]["B"], body["transcripts"]["B"]
    r = deliver(client, sign_record(body))
    assert r.status_code == 200 and r.json()["reason"] == "not_near"
    assert r.json()["trust_tier"] == {"A": "tee", "B": None}


# -- every other condition for met

def test_not_verified(client, phones):
    a, b = phones
    assert a.start().status_code == 200
    assert a.until("verified").status_code == 200
    assert deliver(client, sign_record(make_body(a, b))).json()["reason"] == "no_world_id"
    assert b.start().status_code == 200      # started, not verified
    assert deliver(client, sign_record(make_body(a, b))).json()["reason"] == "role_unverified"


def test_record_of_another_session_id(client, phones):
    a, b = phones
    verify_both(a, b)
    r = deliver(client, sign_record(make_body(a, b, sid="cd" * 16)))
    assert r.json()["met"] is False and r.json()["reason"] == "session_id_mismatch"


def test_other_devices_were_near(client, phones, clock):
    a, b = phones
    verify_both(a, b)
    stranger = Phone(client, clock, "B")
    r = deliver(client, sign_record(make_body(a, stranger)))
    assert r.json()["met"] is False and r.json()["reason"] == "pubkey_mismatch"


def test_same_nullifier_in_state_is_not_met(client, phones, clock):
    """verify refuses this first, so it can only come from a bad row. The answer still doesn't trust the row."""
    a, b = phones
    verify_both(a, b)
    store = client.app.state.store
    store.update(NONCE, "B", clock() // 1000, nullifier=store.get(NONCE, "A")["nullifier"])
    assert why_not_met(store, make_body(a, b)) == "same_human"


# -- check 3: a nullifier can't be reused, including one imported from the old core

def old_core_db(path, *rows):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE wid_nullifiers (rp_id TEXT NOT NULL, action TEXT NOT NULL, nullifier TEXT NOT NULL, "
               "env TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL, created_at INTEGER NOT NULL, "
               "PRIMARY KEY (rp_id, env, action, nullifier))")
    db.executemany("INSERT INTO wid_nullifiers VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()


def test_imported_nullifier_refused(client, phones, fw, settings, tmp_path):
    a, _ = phones
    action = "pop:" + SID
    held = fake_nullifier("A", action)
    src = tmp_path / "old-pop.sqlite"
    old_core_db(src, (settings.rp_id, action, held, "production", "session", "ee" * 16 + ":A", 1_700_000_000),
                ("rp_old", "pop:" + "11" * 16, "0x01", "staging", "session", "11" * 16 + ":B", 1_700_000_001))
    before = src.read_bytes()

    assert import_nullifiers(src, settings.db) == {"read": 2, "added": 2, "kept": 0}
    assert import_nullifiers(src, settings.db) == {"read": 2, "added": 0, "kept": 2}
    assert src.read_bytes() == before
    assert len(client.app.state.store.nullifier_rows()) == 2

    assert a.start().status_code == 200
    r = a.until("verified")
    assert r.status_code == 409 and r.json()["error"] == "nullifier_used", r.text
    s = client.app.state.store.get(NONCE, "A")
    assert s["status"] == "failed" and s["nullifier"] is None
    assert fw.portal_bodies == []
    assert len(client.app.state.store.nullifier_rows()) == 2


def test_import_refuses_its_own_file(tmp_path):
    with pytest.raises(ValueError):
        import_nullifiers(tmp_path / "x.sqlite", tmp_path / "x.sqlite")
