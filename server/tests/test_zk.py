"""Option A proofs (pop/zk.py, Noir oaN_s48 on bb UltraHonk): public vector vs the pinned fixture proof, the real
`bb verify` on it, the upload + delegate endpoints with fakes, artifact download.

Real-proof tests need (skipped otherwise): pinned bb + vk + fixture proofs in ~/.enconomy/zk/pinned (zkmobile/pin),
and for the vector check the spike fixture + optionA-v2 inputs under research/.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from pop import jbl250, popt2, zk
from pop import poseidon2 as p2
from pop.codec import b64d, decode_transcript
from pop.crypto import pub_bytes, sign_raw
from pop.main import Settings, create_app
from pop.store import SqliteStore
from pop.verdict import Reject, verify_record
from tests.sim import Knobs
from tests.sim2 import World2

SERVER = Path(__file__).resolve().parents[1]
ZK = Path(os.environ.get("POP_ZK_SPIKE", SERVER.parent / "research" / "sound-bound" / "spikes" / "zk"))
FIX = ZK / "fixtures" / "popt_v2"
INPUTS = ZK / "optionA-v2" / "inputs"
PIN = Path(os.environ.get("POP_ZK_PINNED", Path.home() / ".enconomy" / "zk" / "pinned"))
BB = PIN / "bin" / "bb"
DEV_ISSUER = bytes.fromhex("04" "9178141b72e5cae00db063dbd38fda4f82a11e1dc8442d2735604719630d99b6"
                           "4b75c24fb3128f0646642e3828848d23348f1e08023f5378425a28cffd1885e3")
VALID_AT = 1790000000   # the fixture's fixed validAt

need_real = pytest.mark.skipif(not (BB.exists() and (PIN / "vk" / "vk").exists() and (PIN / "A" / "proof").exists()),
                               reason="pinned bb / vk / fixture proofs missing")
need_inputs = pytest.mark.skipif(not (FIX.is_dir() and INPUTS.is_dir()), reason="research/ spike not present")


# -- pure helpers

def test_parse_salt():
    assert zk.parse_salt("12") == 12 and zk.parse_salt("0x1f") == 31 and zk.parse_salt(5) == 5
    for bad in (None, "", "-1", "1.5", "0xzz", True, 1 << 248, str(1 << 248)):
        with pytest.raises(ValueError):
            zk.parse_salt(bad)


def test_reason_at():
    want = {0: "transcript_mismatch", 1: "transcript_mismatch", 3: "transcript_mismatch", 4: "transcript_mismatch",
            5: "issuer_unknown", 8: "issuer_unknown", 9: "transcript_mismatch", 11: "transcript_mismatch"}
    for i, r in want.items():
        assert zk.reason_at(i)[0] == r, i
    assert "validAt" in zk.reason_at(10)[1] and "sample_rate" in zk.reason_at(9)[1]
    assert "code_commit" in zk.reason_at(4)[1] and "halfCommit" in zk.reason_at(11)[1]
    with pytest.raises(Reject) as e:
        zk.compare([1] * 3, [1] * 4)
    assert e.value.reason == "proof_invalid"


# -- the pinned fixture proof (180ca04b_48k, bb 5.0.0-nightly.20260522 -t evm)

def _pinned(role):
    return (PIN / role / "proof").read_bytes(), zk.from_file((PIN / role / "public_inputs").read_bytes())


def _real_verifier(**kw):
    return zk.Verifier(str(BB), zk.Artifacts(), **kw)


@need_inputs
@need_real
@pytest.mark.parametrize("role", ["A", "B"])
def test_public_vector_matches_pinned_proof(role):
    """Server-side vector from the fixture transcript + templates == the proof's 12 public inputs."""
    P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
    fx = json.loads((FIX / "180ca04b_48k.json").read_text())
    wi = json.loads((INPUTS / f"popt2_180ca04b_48k_{role}.input.json").read_text())
    i8 = lambda k: np.array([int(v) - P if int(v) > P // 2 else int(v) for v in wi[k]], dtype=np.int8).tobytes()  # noqa
    raw = bytearray(b64d(fx["roles"][role]["transcript_b64"]))
    raw[177:209] = bytes(32)          # Poseidon7-era root; the vector doesn't use it
    t = decode_transcript(bytes(raw))
    got = zk.public_vector(t, (i8("cIs"), i8("cQs")), (i8("cIp"), i8("cQp")), DEV_ISSUER, VALID_AT,
                           int(fx["roles"][role]["salt_dev"], 16))
    assert got == _pinned(role)[1]


@need_real
def test_real_proof_accepted_and_tampers_rejected():
    v = _real_verifier()
    for role in "AB":
        proof, pub = _pinned(role)
        v.verify(zk.CIRCUIT, proof, pub)
    proof, pub = _pinned("A")
    bad = bytearray(proof)
    bad[5000] ^= 1
    for prf, want in ((bytes(bad), pub), (proof, [pub[0] + 1, *pub[1:]]),           # tampered byte, wrong nonce
                      (proof, [*pub[:4], pub[4] + 1, *pub[5:]]),                     # wrong code_commit
                      (proof, [*pub[:11], pub[11] + 1]), (_pinned("B")[0], pub)):    # wrong halfCommit, B's proof
        with pytest.raises(Reject) as e:
            v.verify(zk.CIRCUIT, prf, want)
        assert e.value.reason == "proof_invalid"
    with pytest.raises(Reject) as e:
        _real_verifier(pins={zk.CIRCUIT: "00" * 32}).verify(zk.CIRCUIT, proof, pub)
    assert e.value.reason == "circuit_unknown"


def test_verifier_unavailable(tmp_path):
    v = zk.Verifier(None, zk.Artifacts(str(tmp_path)))
    assert not v.available(zk.CIRCUIT)
    with pytest.raises(zk.Unavailable):
        v.verify(zk.CIRCUIT, b"x", [0])
    with pytest.raises(Reject) as e:
        v.verify("oa2t_s48", b"x", [0])
    assert e.value.reason == "circuit_unknown"


# -- upload endpoint, fake verifier: "proof" = JSON of the public vector the phone claims

class FakeVerifier:
    def __init__(self):
        self.calls = 0

    def available(self, circuit):
        return circuit in zk.VK_PINS

    def verify(self, circuit, proof, expected):
        self.calls += 1
        if circuit not in zk.VK_PINS:
            raise Reject("circuit_unknown", circuit)
        try:
            got = json.loads(proof)["public"]
        except (ValueError, KeyError, TypeError):
            raise Reject("proof_invalid", "not a proof") from None
        zk.compare(got, expected)


HOLD = "%064x" % p2.hash_n(11, [123456789])


@pytest.fixture
def zk_world(clock, tmp_path):
    def make(d=30, holder=True, v1=(), verifier=None, prover=None, **cfg):
        cfg.setdefault("issuer_key_file", str(tmp_path / "issuer.pem"))
        fv = verifier or FakeVerifier()
        app = create_app(Settings(db=":memory:", allow_unattested=True, now_ms=clock, data_dir=str(tmp_path), **cfg),
                         SqliteStore(":memory:"), verifier=fv, prover=prover)
        w = World2(TestClient(app), clock, d, Knobs(),
                   Knobs(sr=48000, mono_off_ns=9_000_000_000, sync_err_ms=-3, out_lat_ms=25), v1=v1, real_root=False)
        if holder:
            for p in w.phones:
                p.enroll_body = (lambda f: lambda n, c, level="tee": {**f(n, c, level), "holder_commit": HOLD})(p.enroll_body)
        w.pair()
        w.fv, w.app, w.tmp = fv, app, tmp_path
        return w
    return make


def _vector(w, p, *, salt=7, issuer=None, valid_at=None):
    t = p.last["transcript"]
    seed, sr, other = w.doc()["seed_hex"], t["sample_rate"], "B" if p.role == "A" else "A"
    own = popt2.code(jbl250.bed_key(seed, p.role, t["attempt"]), p.role, sr)
    par = popt2.code(jbl250.bed_key(seed, other, t["attempt"]), other, sr)
    return zk.public_vector(t, own, par, issuer or w.app.state.issuer.pub,
                            w.view()["zk_valid_at"] if valid_at is None else valid_at, salt)


def _upload(p, sid, proof: bytes, meta: dict):
    b = "popzkboundary"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"meta\"\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"proof\"; filename=\"p.proof\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + proof + f"\r\n--{b}--\r\n".encode()
    path = f"/v1/session/{sid}/proof"
    h = p.headers("POST", path, body)
    h["content-type"] = f"multipart/form-data; boundary={b}"
    return p.client.post(path, content=body, headers=h)


def _send(w, p, salt=7, circuit=None, **kw):
    proof = json.dumps({"public": _vector(w, p, salt=salt, **kw)}).encode()
    circuit = circuit or zk.CIRCUITS[p.k.sr]
    return _upload(p, w.sid, proof, {"attempt": 0, "circuit": circuit, "salt": str(salt)})


def _near(w):
    out = w.run_attempt(0)
    assert out["B"].json()["state"] == "done" and w.result().json()["verdict"] == "NEAR"


def test_proof_before_verdict(zk_world):
    w = zk_world()
    r = _upload(w.a, w.sid, b"x", {"attempt": 0, "circuit": zk.CIRCUIT, "salt": "1"})
    assert r.status_code == 409 and r.json()["error"] == "bad_state"
    assert w.fv.calls == 0


def test_proof_verified_both_roles(zk_world):
    w = zk_world()
    _near(w)
    rec = w.result().json()
    t0 = rec["t0_ms"]
    assert {k: rec["zk"][k] for k in ("valid_at", "status", "A", "B")} == \
        {"valid_at": t0 // 1000, "status": "none", "A": None, "B": None}
    att = rec["zk"]["code_attest"]["A"]
    assert att["msg_hex"][:12] == b"POPCC1".hex() and att["msg_hex"][-64:] == att["code_commit"]
    assert w.view()["zk_valid_at"] == t0 // 1000
    r = _send(w, w.a)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "verified" and j["zk"]["status"] == "partial" and j["zk"]["A"]["circuit"] == zk.CIRCUIT
    assert "salt" not in j["zk"]["A"] and j["zk"]["A"]["half_commit"] == zk.hexes(_vector(w, w.a))[11]
    assert (w.tmp / "sessions" / w.sid / "proof_A_0.bin").exists()
    assert (w.tmp / j["zk"]["A"]["files"]["public_inputs"]).read_bytes() == zk.to_file(_vector(w, w.a))
    r = _send(w, w.b, salt=99)
    assert r.status_code == 200, r.text
    rec = w.result().json()
    assert rec["zk"]["status"] == "verified" and rec["zk"]["B"]["circuit"] == zk.CIRCUIT
    assert json.loads((w.tmp / "sessions" / w.sid / "result.json").read_text())["zk"]["status"] == "verified"
    assert verify_record(rec)["verdict"] == "NEAR"
    n = w.fv.calls
    assert _send(w, w.a).status_code == 200 and w.fv.calls == n     # same bytes: idempotent, not re-verified
    r = _send(w, w.a, salt=8)
    assert r.status_code == 409 and r.json()["error"] == "already_submitted"


def test_proof_wrong_public_input_then_fixed(zk_world):
    w = zk_world()
    _near(w)
    proof = json.dumps({"public": _vector(w, w.b, salt=5)}).encode()
    r = _upload(w.b, w.sid, proof, {"attempt": 0, "circuit": zk.CIRCUIT, "salt": "6"})   # proof made with salt 5
    assert r.status_code == 400 and r.json()["error"] == "transcript_mismatch" and "public[11]" in r.json()["detail"]
    zkr = w.result().json()["zk"]
    assert zkr["status"] == "rejected" and zkr["B"]["reason"] == "transcript_mismatch"
    r = _send(w, w.b, valid_at=w.view()["zk_valid_at"] + 1)
    assert r.status_code == 400 and "validAt" in r.json()["detail"]
    assert _send(w, w.b).status_code == 200
    assert w.result().json()["zk"]["B"]["status"] == "verified"


def test_proof_wrong_issuer(zk_world):
    w = zk_world()
    _near(w)
    other = pub_bytes(ec.generate_private_key(ec.SECP256R1()).public_key())
    r = _send(w, w.a, issuer=other)
    assert r.status_code == 400 and r.json()["error"] == "issuer_unknown"


def test_credential_from_another_issuer(zk_world):
    """The stored SBcred3 doesn't verify under this server's issuer (e.g. key rotated): refused before the SNARK."""
    w = zk_world()
    _near(w)
    st = w.app.state.store
    d = st.get_device(w.a.device_id)
    d["cred_sig"] = sign_raw(ec.generate_private_key(ec.SECP256R1()), bytes.fromhex(d["cred"])).hex()
    st.put_device(d)
    r = _send(w, w.a)
    assert r.status_code == 400 and r.json()["error"] == "issuer_unknown" and w.fv.calls == 0
    assert w.result().json()["zk"]["A"]["status"] == "rejected"


def test_expired_credential(zk_world):
    w = zk_world(cred_ttl_s=1)          # expiry = enroll + 1 s < t0
    _near(w)
    r = _send(w, w.a)
    assert r.status_code == 400 and r.json()["error"] == "credential_expired" and w.fv.calls == 0
    d = w.app.state.store.get_device(w.a.device_id)
    assert d["cred_expiry"] < w.view()["zk_valid_at"]


def test_wrong_circuit_and_bad_requests(zk_world):
    w = zk_world()
    _near(w)
    r = _send(w, w.a, circuit="oa2t_s44")
    assert r.status_code == 400 and r.json()["error"] == "circuit_unknown"
    good = json.dumps({"public": _vector(w, w.a)}).encode()
    for meta in ({"attempt": 0, "circuit": zk.CIRCUIT}, {"attempt": 0, "circuit": zk.CIRCUIT, "salt": "0x" + "f" * 63},
                 {"attempt": 0, "circuit": zk.CIRCUIT, "salt": "abc"}):
        r = _upload(w.a, w.sid, good, meta)
        assert r.status_code == 400 and r.json()["error"] == "bad_request", meta
    r = _upload(w.a, w.sid, good, {"attempt": 1, "circuit": zk.CIRCUIT, "salt": "7"})
    assert r.status_code == 400 and r.json()["error"] == "bad_attempt"
    r = _upload(w.a, w.sid, b"", {"attempt": 0, "circuit": zk.CIRCUIT, "salt": "7"})
    assert r.status_code == 400
    r = _upload(w.a, w.sid, b"not json", {"attempt": 0, "circuit": zk.CIRCUIT, "salt": "7"})
    assert r.status_code == 400 and r.json()["error"] == "proof_invalid"


def test_no_credential(zk_world):
    w = zk_world(holder=False)
    _near(w)
    r = _send(w, w.a)
    assert r.status_code == 409 and r.json()["error"] == "no_credential"


def test_not_near_and_v1(zk_world):
    w = zk_world(d=100)
    w.run_attempt(0)
    assert w.result().json()["verdict"] == "NOT_NEAR"
    r = _send(w, w.a)
    assert r.status_code == 409 and r.json()["error"] == "bad_state"
    w = zk_world(v1=("B",))
    _near(w)
    r = _upload(w.b, w.sid, b"{}", {"attempt": 0, "circuit": "oa2t_s44", "salt": "1"})
    assert r.status_code == 409 and r.json()["error"] == "bad_state"
    assert _send(w, w.a).status_code == 200


def test_verifier_not_configured(zk_world, tmp_path):
    w = zk_world(verifier=zk.Verifier(None, zk.Artifacts(str(tmp_path))))
    _near(w)
    r = _send(w, w.a)
    assert r.status_code == 503 and r.json()["error"] == "zk_unavailable"
    assert w.result().json()["zk"]["A"] is None
    cfg = w.a.client.get("/v1/config").json()["zk"]
    assert cfg["verifier"] == {zk.CIRCUIT: False} and cfg["circuits"] == {"48000": zk.CIRCUIT}


# -- circuit artifact download

def test_key_download(make_client, tmp_path, monkeypatch):
    kd = tmp_path / "zk"
    kd.mkdir()
    data = os.urandom(300_000)
    sha = hashlib.sha256(data).hexdigest()
    (kd / "oaN_s48.json").write_bytes(data)
    (kd / "oaN_s48.vk").write_bytes(b"not the pinned vk")            # pin mismatch: not served
    monkeypatch.setattr(zk, "ARTIFACTS", {"oaN_s48.json": (len(data), sha, tmp_path / "none"),
                                          "oaN_s48.vk": (17, "00" * 32, tmp_path / "none"),
                                          "bn254_g1_2p20.dat": (1, "00" * 32, tmp_path / "none")})
    c = make_client(zk_dir=str(kd))
    m = c.get("/v1/zk/keys").json()["keys"]
    assert m == [{"circuit": zk.CIRCUIT, "sample_rate": 48000, "file": "oaN_s48.json",
                  "url": "/v1/zk/keys/oaN_s48.json", "size": len(data), "sha256": sha,
                  "vk_sha256": zk.VK_PINS[zk.CIRCUIT]}]
    r = c.get("/v1/zk/keys/oaN_s48.json")
    assert r.status_code == 200 and r.content == data and r.headers["x-pop-sha256"] == sha
    assert r.headers.get("accept-ranges") == "bytes"
    r = c.get("/v1/zk/keys/oaN_s48.json", headers={"Range": "bytes=100000-"})
    assert r.status_code == 206 and r.content == data[100000:]
    assert r.headers["content-range"] == f"bytes 100000-{len(data) - 1}/{len(data)}"
    r = c.get("/v1/zk/keys/oaN_s48.json", headers={"Range": f"bytes={len(data)}-"})
    assert r.status_code == 416
    for name in ("oaN_s48.vk", "bn254_g1_2p20.dat", "oa2t_s48.pk.zst", "..%2Fissuer.pem"):
        assert c.get(f"/v1/zk/keys/{name}").status_code == 404, name
    assert c.get("/v1/config").json()["zk"]["keys"] == "/v1/zk/keys"


# -- delegated proving, fake prover: "proof" = JSON of the public vector read back from the Prover.toml

class FakeProver:
    def available(self, circuit):
        return True

    def prove(self, circuit, toml):
        vals = {ln.split(" = ")[0]: ln.split(" = ", 1)[1] for ln in toml.splitlines()}
        if vals["leaf_s"] == '"666"':
            raise Reject("witness_failed", "acvm: assertion failed")
        return b"", b""


def test_delegate(zk_world):
    w = zk_world(prover=FakeProver())
    _near(w)
    want = _vector(w, w.a)
    pr = w.doc()["per_role"]["A"]
    inputs = {k: 0 for k in zk.PRIVATE_PARAMS}
    inputs.update({"nonce_hi": str(want[0]), "nonce_lo": str(want[1]), "attempt": want[2], "role_b": False,
                   "code_commit": str(want[4]), "issuer": [str(x) for x in want[5:9]], "sr": want[9],
                   "valid_at": want[10], "t": list(b64d(pr["transcript_b64"])), "salt": "7", "leaf_s": "1"})
    path = f"/v1/session/{w.sid}/proof/delegate"

    def post(body):
        return w.a.client.post(path, content=json.dumps(body).encode(),
                               headers={**w.a.headers("POST", path, json.dumps(body).encode()),
                                        "content-type": "application/json"})
    bad = {**inputs, "code_commit": str(want[4] + 1)}
    r = post({"attempt": 0, "circuit": zk.CIRCUIT, "salt": "7", "inputs": bad})
    assert r.status_code == 400 and "code_commit" in r.json()["detail"]
    r = post({"attempt": 0, "circuit": zk.CIRCUIT, "salt": "7", "inputs": {**inputs, "t": [0] * 311}})
    assert r.status_code == 400 and "inputs.t" in r.json()["detail"]
    r = post({"attempt": 0, "circuit": zk.CIRCUIT, "salt": "7", "inputs": {**inputs, "bogus": 1}})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    r = post({"attempt": 0, "circuit": zk.CIRCUIT, "salt": "7", "inputs": {**inputs, "leaf_s": "666"}})
    assert r.status_code == 202 and r.json()["zk"]["A"]["status"] == "proving", r.text
    for _ in range(50):
        z = w.result().json()["zk"]["A"]
        if z["status"] != "proving":
            break
        time.sleep(0.05)
    assert z["status"] == "rejected" and z["reason"] == "witness_failed" and z["prover"] == "server"
