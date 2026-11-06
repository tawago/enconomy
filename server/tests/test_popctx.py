"""PopCtx vectors (reference research/worldid/prototypes/ctxnonce/vec.py) + session create."""
import pytest

from pop import popctx
from pop.popctx import DOMAIN, keccak
from tests.phones import Phone

CHAIN = 480
CONSUMER = "0x5afe5afe5afe5afe5afe5afe5afe5afe5afe5afe"
GUARD = "0x6a7d6a7d6a7d6a7d6a7d6a7d6a7d6a7d6a7d6a7d"
POOL = "0x9001900190019001900190019001900190019001"
CTX = bytes(range(0xa0, 0xc0))
NB = 1790000000
SID = "00112233445566778899aabbccddeeff"

G_NONCE = "2b9a8528bf222c8cf60dd97fb416183376bd4bc5425b29c02583518590ef75c9"


def u256(n):
    return n.to_bytes(32, "big")


def addr(a):
    return bytes(12) + bytes.fromhex(a[2:])


def test_domain():
    assert DOMAIN.hex() == "2c71bde9118937099ebb172d5845794f571cc2982d44a563b229d1ea0db2af2f"
    assert keccak(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"  # not sha3


def test_g_vector():
    assert len(popctx.preimage(CHAIN, CONSUMER, CTX, NB, SID)) == 192
    n = popctx.nonce(CHAIN, CONSUMER, CTX, NB, SID)
    assert n.hex() == G_NONCE
    assert popctx.nonce(CHAIN, CONSUMER, "0x" + CTX.hex(), NB, bytes.fromhex(SID)) == n


def test_n_vector():
    safe2 = "0x3fad7600f309b0c3d60a57023b0262460b0603dc"
    h1 = "0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5"
    n = popctx.nonce(480, safe2, h1, NB, SID)
    assert n.hex() == "9fc7507c663ae43d4f8d56ba4b805fdf9e928e565141666a47630aa7fd04b121"


def test_pool_vector():
    assert popctx.nonce(CHAIN, POOL, CTX, NB, SID).hex() == \
        "ab8e50bb766db52b752932e48a63148cf015ac1a17c1345c35d4765f51027d66"


def test_traps_differ():
    """Wrong encodings give the documented trap hashes, never the real nonce."""
    s = b"pop-ctx-v1"
    sid = bytes.fromhex(SID)

    def str_dom(consumer):
        return keccak(u256(0xc0) + u256(CHAIN) + addr(consumer) + CTX + u256(NB) + sid + bytes(16)
                      + u256(len(s)) + s + bytes(32 - len(s))).hex()

    traps = {
        str_dom(GUARD): "5acffbeffd0ba155be27ac0beba39e9100dd749fc15b72ca842a6855cf78becf",
        str_dom(CONSUMER): "36603c76b65742d4039f5fb98950286cfeac74c033b263139045e8beaf472430",
        popctx.nonce(CHAIN, GUARD, CTX, NB, SID).hex(): "a0b4077ef6736018b1ddbc33a5d4b3e3c28a211f1a52566e6d400f7aecd6ff8b",
        keccak(DOMAIN + u256(CHAIN) + addr(CONSUMER) + CTX + u256(NB) + bytes(16) + sid).hex():
            "a3993cf3f5bce4adc7c16d5e5c9c50e78dbde87ce9e1b933ad53fc8665440661",
    }
    for got, want in traps.items():
        assert got == want and got != G_NONCE


def test_bad_inputs():
    with pytest.raises(ValueError):
        popctx.nonce(CHAIN, CONSUMER[:-2], CTX, NB, SID)
    with pytest.raises(ValueError):
        popctx.nonce(CHAIN, CONSUMER, CTX[:31], NB, SID)
    with pytest.raises(ValueError):
        popctx.nonce(CHAIN, CONSUMER, CTX, NB, SID[:-2])
    with pytest.raises(ValueError):
        popctx.nonce(CHAIN, CONSUMER, CTX, 1 << 64, SID)


# -- POST /v1/session with a plain context: bound into the nonce

PLAIN = {"chain_id": 11155111, "consumer": CONSUMER, "ctx_hash": "0x" + CTX.hex()}


@pytest.fixture
def ctx_phones(make_client, clock):
    def make(**kw):
        c = make_client(**kw)
        a, b = Phone(c, clock, "Alice", "Pixel 8"), Phone(c, clock, "Bob", "Galaxy S23")
        assert a.enroll().status_code == 200 and b.enroll().status_code == 200
        return a, b
    return make


def test_create_with_context(ctx_phones, clock):
    a, b = ctx_phones()
    r = a.post("/v1/session", {"context": PLAIN})
    assert r.status_code == 200, r.text
    c = r.json()
    nb = clock() // 1000
    assert c["not_before"] == nb and c["context"] == PLAIN
    assert c["nonce"] == popctx.nonce(11155111, CONSUMER, CTX, nb, c["session_id"]).hex()
    # the guest gets the nonce at confirm, as in any plain session
    v = b.post(f"/v1/session/{c['session_id']}/join", {"join_token": c["join_token"]}).json()
    assert v["nonce"] is None and v["context"] == PLAIN and v["not_before"] == nb


def test_plain_sessions_unchanged(ctx_phones):
    a, b = ctx_phones()
    for body in (None, {}):
        c = (a.post("/v1/session") if body is None else a.post("/v1/session", body)).json()
        assert c["context"] is None and len(c["nonce"]) == 64
    v = b.post(f"/v1/session/{c['session_id']}/join", {"join_token": c["join_token"]}).json()
    assert v["nonce"] is None
    n1 = a.post("/v1/session").json()["nonce"]
    n2 = a.post("/v1/session").json()["nonce"]
    assert n1 != n2  # random


def test_early_nonce(ctx_phones):
    a, b = ctx_phones()
    c = a.post("/v1/session", {"early_nonce": True}).json()
    v = b.post(f"/v1/session/{c['session_id']}/join", {"join_token": c["join_token"]}).json()
    assert v["nonce"] == c["nonce"]

    c = a.post("/v1/session").json()
    sid = c["session_id"]
    assert b.post(f"/v1/session/{sid}/join", {"join_token": c["join_token"]}).json()["nonce"] is None
    assert a.post(f"/v1/session/{sid}/confirm").json()["nonce"] is None
    assert b.post(f"/v1/session/{sid}/confirm").json()["nonce"] == c["nonce"]


@pytest.mark.parametrize("body,status,code", [
    ({"early_nonce": "yes"}, 400, "bad_request"),
    ({"early_nonce": None}, 400, "bad_request"),
    ({"context": {**PLAIN, "kind": "x"}}, 400, "bad_context"),
    ({"context": {k: PLAIN[k] for k in ("chain_id", "consumer")}}, 400, "bad_context"),
    ({"context": {**PLAIN, "chain_id": 4801}}, 400, "bad_chain"),
    ({"context": {**PLAIN, "chain_id": "11155111"}}, 400, "bad_chain"),
    ({"context": {**PLAIN, "consumer": CONSUMER.upper().replace("0X", "0x")}}, 400, "bad_request"),
    ({"context": {**PLAIN, "ctx_hash": "0x" + CTX.hex()[:-2]}}, 400, "bad_request"),
    ({"context": "x"}, 400, "bad_request"),
])
def test_create_rejects(ctx_phones, body, status, code):
    a, _ = ctx_phones()
    r = a.post("/v1/session", body)
    assert r.status_code == status and r.json()["error"] == code, r.text
