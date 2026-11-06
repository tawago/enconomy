"""The refusals that protect the money: each one ends with no attestation and no relay job."""
from __future__ import annotations

import copy

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, encode_dss_signature

from backend import attester
from backend.main import create_app
from backend.safe_tx import TAG, parse_safe_tx, safe_tx_hash
from tests.helpers import CHAIN, NOW_MS, SAFE, SID, T0_MS, VECTOR, Phone, near_record, tx


def register(client, t=None, chain_id=CHAIN) -> str:
    r = client.post("/v1/spends", json={"chain_id": chain_id, "safe": SAFE, "safe_tx": t or tx()})
    assert r.status_code == 200, r.text
    return r.json()["ctx_hash"]


def sign_both(client, ctx_hash, phones) -> None:
    for p in phones:
        r = client.post(f"/v1/spends/{ctx_hash}/owner-sig", json=p.owner_sig(ctx_hash))
        assert r.status_code == 200, r.text


def seed(client, t, chain_id=CHAIN) -> str:
    """A row that got past registration some other way."""
    h = "0x" + safe_tx_hash(chain_id, bytes.fromhex(SAFE[2:]), parse_safe_tx(t)).hex()
    client.app.state.store.put_spend(h, chain_id, SAFE, t, {"case": "seeded"})
    return h


def assert_refused(client, wakes, r, status, code, sid=SID) -> None:
    assert (r.status_code, r.json()["error"]) == (status, code), r.text
    store = client.app.state.store
    assert store.get_attestation(sid) is None
    assert store.job(sid) is None
    assert wakes == []


# -- happy path

def test_near_signs_once_and_queues(client, wakes, phones, attest_key):
    a, b = phones
    h = register(client)
    assert client.get(f"/v1/spends/{h}").json()["safe_tx"] == tx()
    assert client.get(f"/v1/spends/{h}/relay").json() == {"status": "none"}
    sign_both(client, h, phones)

    rec = near_record(a, b, h)
    r = client.post(f"/v1/spends/{h}/presence", json=rec)
    assert r.status_code == 200, r.text
    att = r.json()["att"]

    # expiry comes from the record: t0 + 1.5 s finish + ttl
    assert att["expiry"] == (T0_MS + 1500) // 1000 + 900
    assert att["v"] == TAG.decode() and att["pair_tag"] == "0x" + attester.PAIR_TAG.hex()
    assert att["dev_a"] == "0x" + attester.dev_hash(a.pub.hex()).hex()
    digest = attester.tagged_digest(TAG, CHAIN, SAFE, h, attester.PAIR_TAG, attester.dev_hash(a.pub.hex()),
                                    attester.dev_hash(b.pub.hex()), att["expiry"])
    assert att["digest"] == "0x" + digest.hex()
    der = encode_dss_signature(int(att["r"], 16), int(att["s"], 16))
    attest_key.public_key().verify(der, digest, ec.ECDSA(Prehashed(hashes.SHA256())))
    assert len(bytes.fromhex(att["tail_hex"][2:])) == 172

    assert client.get(f"/v1/spends/{h}/relay").json() == {"status": "pending", "session_id": SID, "result": None}
    assert len(wakes) == 1

    # the other phone delivers too: same bytes, same job, one more wake as the retry
    again = client.post(f"/v1/spends/{h}/presence", json=rec)
    assert again.status_code == 200 and again.json()["att"] == att
    assert len(wakes) == 2


def test_config_serves_the_attest_key(client, attest_key):
    n = attest_key.public_key().public_numbers()
    cfg = client.get("/v1/config").json()
    assert cfg["attest"]["qx"] == "0x%064x" % n.x and cfg["attest"]["qy"] == "0x%064x" % n.y
    assert cfg["owner_msg_tag"] == "pop-safe-owner-v1"
    assert cfg["tokens"][0]["symbol"] == "USDC"


# -- (1) the allowlist

BAD_TX = tx(value="0", data="0x095ea7b3" + "00" * 64)     # an approve: 0 ETH, not on the list


def test_registration_refuses_a_bad_tx(client):
    r = client.post("/v1/spends", json={"chain_id": CHAIN, "safe": SAFE, "safe_tx": BAD_TX})
    assert (r.status_code, r.json()["error"], r.json()["detail"]) == (400, "context_refused", "unknown_call")


def test_good_near_does_not_sign_a_bad_tx(client, wakes, phones):
    a, b = phones
    h = seed(client, BAD_TX)
    sign_both(client, h, phones)
    r = client.post(f"/v1/spends/{h}/presence", json=near_record(a, b, h))
    assert_refused(client, wakes, r, 400, "context_refused")


# -- (2) the presence signature

def test_forged_record_refused(client, wakes, phones):
    a, b = phones
    h = register(client)
    sign_both(client, h, phones)
    other = ec.generate_private_key(ec.SECP256R1())
    r = client.post(f"/v1/spends/{h}/presence", json=near_record(a, b, h, key=other))
    assert_refused(client, wakes, r, 401, "bad_record_signature")


@pytest.mark.parametrize("change", [lambda b: b.update(verdict="FAR"),
                                    lambda b: b["devices"]["B"].update(attested=True),
                                    lambda b: b["context"].update(ctx_hash="0x" + "00" * 32)])
def test_altered_record_refused(client, wakes, phones, change):
    a, b = phones
    b.attested = False
    h = register(client)
    sign_both(client, h, phones)
    rec = copy.deepcopy(near_record(a, b, h))
    change(rec["body"])
    r = client.post(f"/v1/spends/{h}/presence", json=rec)
    assert_refused(client, wakes, r, 401, "bad_record_signature")


def test_the_cores_own_vector_verifies_and_stays_unattestable(client, wakes):
    """A record the core's real code signed gets past the signature check here. Its context is null: no spend."""
    h = register(client)
    r = client.post(f"/v1/spends/{h}/presence", json=VECTOR["record"])
    assert_refused(client, wakes, r, 403, "context_mismatch", VECTOR["record"]["body"]["session_id"])


# -- (3) NEAR, this transaction, attested per the record

def test_not_near_refused(client, wakes, phones):
    a, b = phones
    h = register(client)
    sign_both(client, h, phones)
    r = client.post(f"/v1/spends/{h}/presence", json=near_record(a, b, h, verdict="FAR"))
    assert_refused(client, wakes, r, 403, "not_near")


def test_wrong_ctx_hash_refused(client, wakes, phones):
    a, b = phones
    h = register(client)
    other = register(client, tx(nonce="1"))
    sign_both(client, h, phones)
    r = client.post(f"/v1/spends/{h}/presence", json=near_record(a, b, other))
    assert_refused(client, wakes, r, 403, "context_mismatch")


@pytest.mark.parametrize("who", ["A", "B"])
def test_attested_false_refused(client, wakes, who):
    a, b = Phone(attested=who != "A"), Phone(attested=who != "B")
    h = register(client)
    sign_both(client, h, (a, b))
    r = client.post(f"/v1/spends/{h}/presence", json=near_record(a, b, h))
    assert_refused(client, wakes, r, 403, "unattested_device")


# -- the rest of the order

def test_wrong_chain_refused(client, wakes, phones):
    a, b = phones
    h = register(client, chain_id=480)
    sign_both(client, h, phones)
    r = client.post(f"/v1/spends/{h}/presence", json=near_record(a, b, h, chain_id=480))
    assert_refused(client, wakes, r, 403, "bad_chain")


def test_missing_owner_sig_refused_then_retry_works(client, wakes, phones):
    a, b = phones
    h = register(client)
    client.post(f"/v1/spends/{h}/owner-sig", json=a.owner_sig(h))
    rec = near_record(a, b, h)
    assert_refused(client, wakes, client.post(f"/v1/spends/{h}/presence", json=rec), 409, "owner_sigs_missing")
    client.post(f"/v1/spends/{h}/owner-sig", json=b.owner_sig(h))
    assert client.post(f"/v1/spends/{h}/presence", json=rec).status_code == 200


def test_old_record_gets_no_fresh_attestation(client, wakes, phones):
    a, b = phones
    h = register(client)
    sign_both(client, h, phones)
    r = client.post(f"/v1/spends/{h}/presence", json=near_record(a, b, h, t0_ms=NOW_MS - 1_000_000))
    assert_refused(client, wakes, r, 403, "expired")


def test_owner_sig_must_verify(client, phones):
    a, b = phones
    h = register(client)
    other = register(client, tx(nonce="1"))
    r = client.post(f"/v1/spends/{h}/owner-sig", json=a.owner_sig(other))
    assert (r.status_code, r.json()["error"]) == (400, "bad_owner_sig")


# -- startup

def test_missing_attest_key_refuses_to_start(settings, tmp_path):
    settings.attest_key_file = tmp_path / "gone.pem"
    with pytest.raises(FileNotFoundError):
        create_app(settings)
    assert not (tmp_path / "gone.pem").exists()     # no autogen


def test_attest_key_equal_to_core_key_refuses_to_start(settings, attest_key):
    settings.core_pubkey = attester.public_bytes(attest_key)
    with pytest.raises(ValueError, match="presence key"):
        create_app(settings)
