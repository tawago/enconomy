"""Presence record intake. The vector is the same file the core tests against, so this is the interop proof."""
import base64
import copy
import hashlib

from cryptography.hazmat.primitives.asymmetric import ec

from backend.core import TAG_RECORD, TAG_STATEMENT, canonical, verify_signed
from tests.helpers import CORE_PUB, VECTOR, sign_raw, sign_record

RECORD = VECTOR["record"]
SID = RECORD["body"]["session_id"]


def post(client, rec):
    return client.post("/v1/presence", json=rec)


def test_vector_canonical_bytes_and_signatures():
    assert canonical(RECORD["body"]).hex() == VECTOR["record_canonical_hex"]
    assert canonical(VECTOR["statement"]["body"]).hex() == VECTOR["statement_canonical_hex"]
    assert VECTOR["record_tag"].encode() == TAG_RECORD and VECTOR["statement_tag"].encode() == TAG_STATEMENT
    assert verify_signed(CORE_PUB, TAG_RECORD, RECORD)
    assert verify_signed(CORE_PUB, TAG_STATEMENT, VECTOR["statement"])


def test_tags_are_not_interchangeable():
    assert not verify_signed(CORE_PUB, TAG_STATEMENT, RECORD)
    assert not verify_signed(CORE_PUB, TAG_RECORD, VECTOR["statement"])


def test_vector_record_accepted(client):
    r = post(client, RECORD)
    assert r.status_code == 200, r.text
    assert r.json() == {"session_id": SID, "status": "stored"}
    row = client.app.state.store.get_record(SID)
    assert row["verdict"] == "NEAR" and row["sig_b64"] == RECORD["sig_b64"]
    assert canonical(RECORD["body"]).decode() == row["body"]    # still verifies from what's stored


def test_idempotent(client):
    assert post(client, RECORD).json()["status"] == "stored"
    assert post(client, RECORD).json()["status"] == "unchanged"
    assert client.app.state.store.db.execute("SELECT count(*) FROM presence_records").fetchone()[0] == 1


def test_tampered_or_unsigned_refused(client):
    for field, value in (("verdict", "NOT_NEAR"), ("session_id", "0" * 32), ("flight_cm", "1.00")):
        rec = copy.deepcopy(RECORD)
        rec["body"][field] = value
        r = post(client, rec)
        assert r.status_code == 401 and r.json()["error"] == "bad_record_signature", field
    assert post(client, {"body": RECORD["body"]}).status_code == 401
    assert post(client, {}).status_code == 401
    assert client.app.state.store.get_record(SID) is None


def test_foreign_key_refused(client):
    r = post(client, sign_record(RECORD["body"], ec.generate_private_key(ec.SECP256R1())))
    assert r.status_code == 401


def test_float_refused(client):
    """The core never signs a float, so one can't verify."""
    rec = copy.deepcopy(RECORD)
    rec["body"]["flight_cm"] = 30.37
    assert post(client, rec).status_code == 401


def test_rechecks_what_the_signature_covers(client):
    """Signed by the core and still refused: these don't lean on its word."""
    def bad(change):
        body = copy.deepcopy(RECORD["body"])
        change(body)
        r = post(client, sign_record(body))
        assert r.status_code == 400 and r.json()["error"] == "bad_record", r.text

    def changed_transcript(b):
        raw = base64.b64decode(b["transcripts"]["A"]["transcript_b64"]) + b"x"
        b["transcripts"]["A"].update(transcript_b64=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())

    bad(lambda b: b.update(format="other"))
    bad(lambda b: b.update(session_id="../nope"))
    bad(lambda b: b["devices"]["A"].update(device_id="0" * 32))
    bad(lambda b: b["devices"]["A"].update(pubkey="04ab"))
    bad(lambda b: b["devices"]["A"].update(pubkey=b["devices"]["B"]["pubkey"]))
    bad(lambda b: b["transcripts"]["A"].update(sha256="0" * 64))
    bad(lambda b: b["transcripts"]["A"].update(sig_b64=b["transcripts"]["B"]["sig_b64"]))
    bad(lambda b: b["transcripts"]["A"].update(transcript_b64="!!"))
    bad(lambda b: b["transcripts"].pop("B"))
    bad(lambda b: b["devices"].pop("B"))
    bad(changed_transcript)
    assert client.app.state.store.get_record(SID) is None


def test_device_signature_from_the_wrong_key_refused(client):
    body = copy.deepcopy(RECORD["body"])
    other = ec.generate_private_key(ec.SECP256R1())
    raw = base64.b64decode(body["transcripts"]["A"]["transcript_b64"])
    body["transcripts"]["A"]["sig_b64"] = base64.b64encode(sign_raw(other, raw)).decode()
    r = post(client, sign_record(body))
    assert r.status_code == 400 and "signature" in r.json()["detail"]


def later(status="verified", pair=None) -> dict:
    body = copy.deepcopy(RECORD["body"])
    body["zk"].update(status=status, A={"status": "verified"}, B={"status": "verified"}, pair=pair)
    return sign_record(body)


def test_later_zk_record_accepted(client):
    assert post(client, RECORD).status_code == 200
    r = post(client, later())
    assert r.status_code == 200 and r.json()["status"] == "updated"
    assert '"status":"verified"' in client.app.state.store.get_record(SID)["body"]


def test_older_zk_record_does_not_undo_a_newer_one(client):
    assert post(client, later()).status_code == 200
    r = post(client, RECORD)
    assert r.status_code == 200 and r.json()["status"] == "unchanged"
    assert '"status":"verified"' in client.app.state.store.get_record(SID)["body"]


def test_later_record_differing_outside_zk_is_conflict(client):
    assert post(client, RECORD).status_code == 200
    for field, value in (("verdict", "NOT_NEAR"), ("t0_ms", 1), ("attempt", 1), ("flight_cm", "1.00")):
        body = copy.deepcopy(RECORD["body"])
        body[field] = value
        r = post(client, sign_record(body))
        assert r.status_code == 409 and r.json()["error"] == "record_conflict", field
    assert client.app.state.store.get_record(SID)["sig_b64"] == RECORD["sig_b64"]


def test_non_near_record_with_what_it_has(client):
    """A final failure has a record too, maybe with no transcripts. Stored, signature checked."""
    body = copy.deepcopy(RECORD["body"])
    body.update(verdict="NOT_NEAR", reason="too_far", transcripts={})
    assert post(client, sign_record(body)).json()["status"] == "stored"


def test_intake_wakes_the_worker(client):
    woken = []
    client.app.state.worker.wake = lambda: woken.append(1)
    assert post(client, RECORD).status_code == 200
    assert woken == [1]
    assert post(client, RECORD).status_code == 200
    assert woken == [1, 1]  # nothing new, but still undone: a redelivery is its retry
    client.app.state.store.set_session(SID, status="ignored")
    assert post(client, RECORD).status_code == 200
    assert woken == [1, 1]  # done: nothing to do


def test_oversized_body_refused(client):
    assert client.post("/v1/presence", content=b" " * ((1 << 20) + 1)).status_code == 413
