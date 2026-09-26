"""SAFE consumer (worldid spec 02 §7.4): safeTxHash vectors, allowlist, owner-sig route, pop-safe-v2 attestation."""
from __future__ import annotations

import hashlib

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature, Prehashed
from cryptography.hazmat.primitives import hashes

from pop import attest
from pop.consumers import safe_tx as S
from pop.crypto import device_id, pub_bytes, sign_raw
from pop.errors import PopError
from tests.phones import Phone
from tests.sim2 import Knobs, World2
from tests.test_worldid import FakeWorld, verified_pair

SAFE480 = "0x3fad7600f309b0c3d60a57023b0262460b0603dc"
Z = "0x" + "00" * 20
WLD = "0x2cfc85d8e48f8eab294be644d9e25c3030863003"
USDC480 = "0x79a02482a880bce3f13e09da970dc34db4cd24d1"
USDC_SEP = "0x1c7d4b196cb0c7b01d743fbc6116a902379c7238"
MSCO = "0xa83c336b20401af773b6219ba5027174338d1836"
SEP = 11155111
SAFE = "0x" + "5afe" * 10


def tx(**k) -> dict:
    t = {"to": "0x" + "11" * 20, "value": "0", "data": "0x", "operation": 0, "safe_tx_gas": "0", "base_gas": "0",
         "gas_price": "0", "gas_token": Z, "refund_receiver": Z, "nonce": "0"}
    t.update(k)
    return t


def word(a: str) -> str:
    return a[2:].rjust(64, "0")


ROW = {
    1: (480, tx(value=str(10 ** 16)), "0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5"),
    2: (480, tx(to=WLD, data="0xa9059cbb" + word("0x" + "22" * 20) + "%064x" % (15 * 10 ** 17)),
        "0x320418179acf57e8607ddcb3f82e113cb45d0d7579b95ccb81ee04afc056a3ce"),
    3: (480, tx(to=SAFE480, data="0xe19a9dd9" + word("0x" + "33" * 20)),
        "0x29e1fbc2114cbf3e89bf83db0a08b3faf7b502b2fc6d60691e0fcf132df7c2f7"),
    4: (480, tx(nonce="42", to=MSCO, value="123456789", data="0xdeadbeef00", operation=1, safe_tx_gas="50000",
                base_gas="21000", gas_price="7", gas_token=USDC480, refund_receiver="0x" + "44" * 20),
        "0x321d09105a40b0d115e6f2b294208a0fac9eb117f88c3d7ca5e036484aa591e1"),
}
ROW[5] = (4801, ROW[4][1], "0xb0bcdc64af0c7fe223a8b673357104673dc659be0b9c98a9970d932a3c8cb2ac")


def ctx_of(chain: int, t: dict, safe: str = SAFE480, h: str | None = None) -> dict:
    if h is None:
        h = "0x" + S.safe_tx_hash(chain, bytes.fromhex(safe[2:]), S.parse_safe_tx(t)).hex()
    return {"kind": "safe-tx", "chain_id": chain, "consumer": safe, "ctx_hash": h, "safe_tx": t}


# -- hashes + validate (§7.1, §7.2)

@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_safe_tx_hash_vectors(n):
    chain, t, h = ROW[n]
    assert "0x" + S.safe_tx_hash(chain, bytes.fromhex(SAFE480[2:]), S.parse_safe_tx(t)).hex() == h


@pytest.mark.parametrize("n", [1, 2])
def test_validate_accepts(n):
    chain, t, h = ROW[n]
    assert S.validate(ctx_of(chain, t, h=h)) == bytes.fromhex(h[2:])


@pytest.mark.parametrize("n,reason", [(3, "self_call"), (4, "delegatecall"), (5, "delegatecall")])
def test_validate_refuses(n, reason):
    chain, t, h = ROW[n]
    with pytest.raises(PopError) as e:
        S.validate(ctx_of(chain, t, h=h))
    assert (e.value.status, e.value.code, e.value.detail) == (400, "context_refused", reason)


@pytest.mark.parametrize("t,reason", [
    (tx(value="1", safe_tx_gas="1"), "gas_refund_fields"),
    (tx(value="1", refund_receiver="0x" + "44" * 20), "gas_refund_fields"),
    (tx(value="1", data="0x00"), "value_with_call"),
    (tx(value="0"), "unknown_call"),                                             # zero native transfer
    (tx(to=WLD, data="0xa9059cbb" + word("0x" + "22" * 20) + "%064x" % 1), "unknown_call"),  # not a Sepolia token
    (tx(to=USDC_SEP, data="0xa9059cbb" + word("0x" + "22" * 20) + "%064x" % 0), "unknown_call"),  # amount 0
    (tx(to=USDC_SEP, data="0x095ea7b3" + word("0x" + "22" * 20) + "%064x" % 1), "unknown_call"),  # approve
    (tx(to=USDC_SEP, data="0xa9059cbb" + "ff" * 12 + "22" * 20 + "%064x" % 1), "unknown_call"),  # dirty address word
])
def test_allowlist_sepolia(t, reason):
    with pytest.raises(PopError) as e:
        S.validate(ctx_of(SEP, t, safe=SAFE))
    assert e.value.detail == reason


def test_allowlist_sepolia_usdc_and_native():
    usdc = tx(to=USDC_SEP, data="0xa9059cbb" + word("0x" + "22" * 20) + "%064x" % 1_500_000)
    assert S.allowlist(SEP, bytes.fromhex(SAFE[2:]), S.parse_safe_tx(usdc)) == {
        "case": "erc20", "token": "USDC", "decimals": 6, "to": "0x" + "22" * 20, "amount": "1500000"}
    S.validate(ctx_of(SEP, usdc, safe=SAFE))
    S.validate(ctx_of(SEP, tx(value="1"), safe=SAFE))


def test_validate_mismatch_and_shape():
    chain, t, h = ROW[1]
    with pytest.raises(PopError) as e:
        S.validate(ctx_of(chain, t, h=h[:-1] + ("0" if h[-1] != "0" else "1")))
    assert e.value.code == "context_mismatch"
    for bad, field in ((tx(value="01"), "value"), (tx(operation="0"), "operation"), (tx(operation=True), "operation"),
                       (tx(to="0x" + "AB" * 20), "to"), (tx(data="0x0"), "data"), ({**tx(), "x": 1}, "safe_tx_keys"),
                       (tx(nonce=str(2 ** 256)), "nonce")):
        with pytest.raises(PopError) as e:
            S.parse_safe_tx(bad)
        assert (e.value.status, e.value.code, e.value.detail) == (400, "bad_context", field)


# -- routes

@pytest.fixture
def two(make_client, clock):
    """A client on Sepolia with safe-tx sessions allowed (RP set) and two attested phones A=0xA1, B=0xB1."""
    def make(**kw):
        kw.setdefault("worldid_rp_id", "rp_0123456789abcdef")
        c = make_client(**kw)
        ps = []
        for name, k in (("Alice", 0xA1), ("Bob", 0xB1)):
            p = Phone(c, clock, name, "Pixel 8")
            p.sk = ec.derive_private_key(k, ec.SECP256R1())
            p.pub = pub_bytes(p.sk.public_key())
            p.device_id = device_id(p.pub)
            assert p.enroll().status_code == 200
            ps.append(p)
        return c, ps[0], ps[1]
    return make


def open_session(c, a, b, t=None, safe=SAFE):
    ctx = ctx_of(SEP, t or tx(to="0x" + "be" * 20, value="500000000000000"), safe=safe)
    r = a.post("/v1/session", {"context": ctx})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert b.post(f"/v1/session/{sid}/join", {"join_token": r.json()["join_token"]}).status_code == 200
    return sid, ctx


def test_create_safe_tx_session(two):
    c, a, b = two()
    sid, ctx = open_session(c, a, b)
    v = a.get(f"/v1/session/{sid}").json()
    assert v["context"] == ctx and v["policy"] == {"human": "worldid"}
    bad = {**ctx, "safe_tx": {**ctx["safe_tx"], "to": ctx["consumer"]}}
    bad["ctx_hash"] = "0x" + S.safe_tx_hash(SEP, bytes.fromhex(SAFE[2:]), S.parse_safe_tx(bad["safe_tx"])).hex()
    r = a.post("/v1/session", {"context": bad})
    assert r.status_code == 400 and r.json() == {"error": "context_refused", "detail": "self_call"}
    r = a.post("/v1/session", {"context": {**ctx, "chain_id": 4801}})
    assert r.status_code == 400 and r.json()["error"] == "bad_chain"
    r = a.post("/v1/session", {"context": {**ctx, "ctx_hash": ROW[1][2]}})
    assert r.status_code == 400 and r.json()["error"] == "context_mismatch"


def test_config(two):
    c, _, _ = two()
    cfg = c.get("/v1/config").json()
    assert cfg["chain"] == {"chain_id": SEP}
    assert cfg["safe"]["owner_msg_tag"] == "pop-safe-owner-v1" and USDC_SEP in cfg["safe"]["tokens"]
    sk = attest.load_key(c.app.state.cfg.attest_key_file)
    assert cfg["attest"] == attest.public(sk) and cfg["attest"]["qx"].startswith("0x")


def test_owner_sig_vector_and_route(two):
    # §4.3 vector: key 0xA1, ctx_hash = row 1, the published (high-s) r||s must verify, not be regenerated
    r_ = "76a33345d9c2e60b4cdab2063ca4f19855b058ba269a1408f9420dcbd7cfe842"
    s_ = "9c52547d6bf37b06a7614c1cd6ede11f15a7fe439aeab9cedd478b652e661fba"
    pk = ec.derive_private_key(0xA1, ec.SECP256R1()).public_key()
    m = S.owner_message(bytes.fromhex(ROW[1][2][2:]))
    assert hashlib.sha256(m).hexdigest() == "e0005ceaee59d61859d4a867fc15897bbfeca13f9c737ebb6959cdde31f2b25d"
    pk.verify(encode_dss_signature(int(r_, 16), int(s_, 16)), m, ec.ECDSA(hashes.SHA256()))

    c, a, b = two()
    sid, ctx = open_session(c, a, b)
    h = bytes.fromhex(ctx["ctx_hash"][2:])
    sig = sign_raw(a.sk, S.owner_message(h))
    assert a.post(f"/v1/session/{sid}/safe/owner-sig", {"sig": "0x" + sig.hex()}).json() == {"ok": True}
    flipped = bytearray(sig); flipped[5] ^= 1
    r = b.post(f"/v1/session/{sid}/safe/owner-sig", {"sig": "0x" + flipped.hex()})
    assert r.status_code == 400 and r.json()["error"] == "bad_owner_sig"
    r = b.post(f"/v1/session/{sid}/safe/owner-sig", {"sig": "0x" + sig.hex()})     # A's sig from B's device
    assert r.status_code == 400 and r.json()["error"] == "bad_owner_sig"
    r = b.post(f"/v1/session/{sid}/safe/owner-sig", {"sig": "0x" + sig.hex().upper()})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    s = c.app.state.store.get_session(sid)
    assert s["safe"]["owner_sigs"] == {"A": "0x" + sig.hex(), "B": None}
    # plain session -> not_safe_tx; done -> too_late
    plain = a.post("/v1/session").json()["session_id"]
    r = a.post(f"/v1/session/{plain}/safe/owner-sig", {"sig": "0x" + sig.hex()})
    assert r.status_code == 409 and r.json()["error"] == "not_safe_tx"
    s["state"] = "done"
    c.app.state.store.put_session(s)
    r = a.post(f"/v1/session/{sid}/safe/owner-sig", {"sig": "0x" + sig.hex()})
    assert r.status_code == 409 and r.json()["error"] == "too_late"


# -- attestation (01 §8.1-§8.4, 02 §7.3 S4.5)

NA = "0x" + "0a" * 32
NB = "0x" + "0b" * 32


def finish(c, sid, a, b, verdict="NEAR", env=("production", "production"), attested=(True, True), sigs=True):
    """Turn a created+joined session into a done one, as the real flow would leave it."""
    store = c.app.state.store
    s = store.get_session(sid)
    from pop.human import pair_tag
    s["human"]["A"].update({"status": "verified", "nullifier": NA, "environment": env[0], "action": "pop:" + sid,
                            "signal_hash": "0x01", "proof": ["1", "2"]})
    s["human"]["B"].update({"status": "verified", "nullifier": NB, "environment": env[1], "action": "pop:" + sid})
    s["human"]["pair_tag"] = pair_tag(NA, NB)
    h = bytes.fromhex(s["context"]["ctx_hash"][2:])
    if sigs:
        s["safe"] = {"owner_sigs": {"A": "0x" + sign_raw(a.sk, S.owner_message(h)).hex(),
                                    "B": "0x" + sign_raw(b.sk, S.owner_message(h)).hex()}}
    s["state"], s["finished_ms"] = "done", s["created_ms"] + 30_000
    devs = {}
    for r, p, at in (("A", a, attested[0]), ("B", b, attested[1])):
        devs[r] = {"device_id": p.device_id, "pubkey": p.pub.hex(), "attested": at, "security_level": "tee"}
    s["result"] = {"verdict": verdict, "reason": None if verdict == "NEAR" else "too_far", "attempt": 0,
                   "flight_cm": 30.0, "devices": devs, "human": s["human"], "transcripts": {}, "zk": None}
    store.put_session(s)
    return s


def test_attestation_near(two):
    c, a, b = two()
    sid, ctx = open_session(c, a, b)
    r = c.get(f"/v1/session/{sid}/attestation")
    assert r.json() == {"v": 1, "session_id": sid, "state": "joined", "verdict": None, "att": None,
                        "att_refused": None}
    s = finish(c, sid, a, b)
    body = c.get(f"/v1/session/{sid}/attestation").json()
    att = body["att"]
    assert body["att_refused"] is None and att["v"] == "pop-safe-v2" and body["verdict"] == "NEAR"
    dev_a, dev_b = hashlib.sha256(a.pub).digest(), hashlib.sha256(b.pub).digest()
    assert att["dev_a"] == "0x" + dev_a.hex() and body["devices"]["A"]["pubkey"] == "0x" + a.pub.hex()
    assert body["devices"]["A"]["device_hash"][2:34] == a.device_id
    expiry = s["finished_ms"] // 1000 + 900
    pre = (b"pop-safe-v2" + SEP.to_bytes(32, "big") + bytes.fromhex(SAFE[2:]) + bytes.fromhex(ctx["ctx_hash"][2:])
           + bytes.fromhex(s["human"]["pair_tag"][2:]) + dev_a + dev_b + expiry.to_bytes(8, "big"))
    assert len(pre) == 199 and att["expiry"] == expiry and att["digest"] == "0x" + hashlib.sha256(pre).hexdigest()
    tail = bytes.fromhex(att["tail_hex"][2:])
    assert len(tail) == 172 and tail.endswith(bytes.fromhex("504f5032"))
    assert tail[:104] == bytes.fromhex(s["human"]["pair_tag"][2:]) + dev_a + dev_b + expiry.to_bytes(8, "big")
    pub = attest.load_key(c.app.state.cfg.attest_key_file).public_key()
    pub.verify(encode_dss_signature(int(att["r"], 16), int(att["s"], 16)), hashlib.sha256(pre).digest(),
               ec.ECDSA(Prehashed(hashes.SHA256())))
    assert body["safe"]["owner_sigs"]["A"] == s["safe"]["owner_sigs"]["A"] and body["safe"]["owner_sigs"]["B"]
    assert body["context"]["safe_tx"] == ctx["safe_tx"] and body["human"]["A"]["nullifier"] == NA
    # cached: identical bytes on the second read
    assert c.get(f"/v1/session/{sid}/attestation").json()["att"] == att


def test_attestation_not_near_hides_owner_sigs(two):
    c, a, b = two()
    sid, _ = open_session(c, a, b)
    finish(c, sid, a, b, verdict="NOT_NEAR")
    body = c.get(f"/v1/session/{sid}/attestation").json()
    assert body["att"] is None and body["att_refused"] == "not_near"
    assert body["safe"] == {"owner_sigs": {"A": None, "B": None}}
    assert c.app.state.store.get_session(sid)["safe"]["owner_sigs"]["A"]       # stored, never published


@pytest.mark.parametrize("env", [("production", "fake"), ("staging", "production"), ("production", "sandbox"),
                                 ("production", None)])
def test_attestation_refuses_nonprod_humans(two, env):
    c, a, b = two()
    sid, _ = open_session(c, a, b)
    finish(c, sid, a, b, env=env)
    body = c.get(f"/v1/session/{sid}/attestation").json()
    assert body["att"] is None and body["att_refused"] == "nonprod_humans"
    assert body["safe"]["owner_sigs"] == {"A": None, "B": None}


def test_attestation_refusals(two):
    c, a, b = two()
    sid, _ = open_session(c, a, b)
    s = finish(c, sid, a, b, attested=(True, False))
    assert c.get(f"/v1/session/{sid}/attestation").json()["att_refused"] == "unattested_device"
    # human missing
    s["human"]["B"]["status"] = "failed"
    c.app.state.store.put_session(s)
    assert c.get(f"/v1/session/{sid}/attestation").json()["att_refused"] == "human_missing"
    # tampered stored context
    s["human"]["B"]["status"] = "verified"
    s["context"]["safe_tx"]["value"] = "1"
    c.app.state.store.put_session(s)
    assert c.get(f"/v1/session/{sid}/attestation").json()["att_refused"] == "context_mismatch"
    # plain session: no attestation endpoint
    plain = a.post("/v1/session").json()["session_id"]
    assert c.get(f"/v1/session/{plain}/attestation").status_code == 404


def test_attestation_unattested_allow(two):
    c, a, b = two()
    sid, _ = open_session(c, a, b)
    finish(c, sid, a, b, attested=(True, False))
    c2 = c.app.state.cfg
    c2.unattested_allow = frozenset({b.device_id})
    assert c.get(f"/v1/session/{sid}/attestation").json()["att"]["v"] == "pop-safe-v2"


def test_attestation_bad_chain(two):
    c, a, b = two()
    sid, _ = open_session(c, a, b)
    finish(c, sid, a, b)
    c.app.state.cfg.chain_id = 4801
    assert c.get(f"/v1/session/{sid}/attestation").json()["att_refused"] == "bad_chain"


def test_full_flow_test_kind_fake_humans(make_client, clock):
    """sim2 phones + fake World ID: test kind gets pop-test-v1, safe-tx with the same fake humans is refused."""
    fw = FakeWorld()
    c = make_client(allow_unattested=True, test_kinds=True, worldid_fake=True, worldid_rp_id="rp_0123456789abcdef",
                    worldid_app_id="app_test", worldid_transport=httpx.MockTransport(fw))

    async def nosleep(_s):
        return None
    c.app.state.worldid.sleep = nosleep
    out = {}
    for ctx in ({"kind": "test", "chain_id": SEP, "consumer": SAFE, "ctx_hash": "0x" + "ab" * 32},
                ctx_of(SEP, tx(value="1"), safe=SAFE)):
        w = World2(c, clock, 30, Knobs(), Knobs(sr=44100, mono_off_ns=9_000_000_000, sync_err_ms=-3, out_lat_ms=25))
        a, b = w.phones
        for p in w.phones:
            assert p.enroll(attested=True).status_code == 200
        sid = verified_pair(c, a, b, {"context": ctx})
        a.post(f"/v1/session/{sid}/confirm")
        v = b.post(f"/v1/session/{sid}/confirm").json()
        for p, q in ((a, b), (b, a)):
            p.sid, p.nonce, p.partner_pub = sid, bytes.fromhex(v["nonce"]), q.pub
        w.sid = sid
        w.run_attempt(0)
        assert w.result().json()["verdict"] == "NEAR"
        out[ctx["kind"]] = c.get(f"/v1/session/{sid}/attestation").json()
    assert out["test"]["att"]["v"] == "pop-test-v1" and out["test"]["att_refused"] is None
    assert out["safe-tx"]["att"] is None and out["safe-tx"]["att_refused"] == "nonprod_humans"
