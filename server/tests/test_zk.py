"""Option A proofs (pop/zk.py): public vector vs the spike, the real SNARK verifier on a real proof, the upload
endpoint with a fake verifier, proving-key download.

Real-proof tests need (skipped otherwise):
  popprover  POP_ZK_VERIFIER or ../app/prover/target/release/popprover (host build)
  vk         POP_ZK_VK_DIR or the spike's optionA-v2/keys/oa2t_s48.vk (read-only)
  proof      POP_ZK_TEST_PROOF or data/zk/test/popt2_180ca04b_48k_A.proof, made once with
             tools/heavy.sh s7-prove popprover prove <spike keys>/oa2t_s48.pk <spike inputs>/popt2_180ca04b_48k_A.input.json <proof>
Each verify loads the 470 MB vk (~5 s) and runs under research/.../zk/tools/heavy.sh when it exists.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from pop import issuer as sbcred
from pop import jbl250, popt2, poseidon7, zk
from pop.codec import b64d, decode_transcript
from pop.crypto import pub_bytes, sign_raw
from pop.main import Settings, create_app
from pop.store import SqliteStore
from pop.verdict import Reject, verify_record
from tests.sim import Knobs
from tests.sim2 import World2

SERVER = Path(__file__).resolve().parents[1]
ZK = SERVER.parent / "research" / "sound-bound" / "spikes" / "zk"
FIX = ZK / "fixtures" / "popt_v2"
INPUTS = ZK / "optionA-v2" / "inputs"
HEAVY = ZK / "tools" / "heavy.sh"
BIN = Path(os.environ.get("POP_ZK_VERIFIER", SERVER.parent / "app" / "prover" / "target" / "release" / "popprover"))
VK_DIR = Path(os.environ.get("POP_ZK_VK_DIR", ZK / "optionA-v2" / "keys"))
PROOF = Path(os.environ.get("POP_ZK_TEST_PROOF", SERVER / "data" / "zk" / "test" / "popt2_180ca04b_48k_A.proof"))
DEV_ISSUER = bytes.fromhex("04" "9178141b72e5cae00db063dbd38fda4f82a11e1dc8442d2735604719630d99b6"
                           "4b75c24fb3128f0646642e3828848d23348f1e08023f5378425a28cffd1885e3")
VALID_AT = 1790000000   # the spike's fixed validAt

need_spike = pytest.mark.skipif(not FIX.is_dir(), reason="research/ spike not present")
need_real = pytest.mark.skipif(not (FIX.is_dir() and BIN.exists() and (VK_DIR / "oa2t_s48.vk").exists()
                                    and PROOF.exists()), reason="popprover / vk / proof artifacts missing")


# -- pure helpers

def test_parse_salt():
    assert zk.parse_salt("12") == 12 and zk.parse_salt("0x1f") == 31 and zk.parse_salt(5) == 5
    for bad in (None, "", "-1", "1.5", "0xzz", True, 1 << 248, str(1 << 248)):
        with pytest.raises(ValueError):
            zk.parse_salt(bad)


def test_reason_at():
    L = 12000
    n = zk.n_public(L)
    assert n == 48011 and zk.n_public(11025) == 44111
    want = {0: "transcript_mismatch", 1: "transcript_mismatch", 3: "transcript_mismatch", 4: "transcript_mismatch",
            6: "transcript_mismatch", 7 + 4 * L - 1: "transcript_mismatch", 7 + 4 * L: "issuer_unknown",
            8 + 4 * L: "issuer_unknown", 9 + 4 * L: "transcript_mismatch", n - 1: "transcript_mismatch"}
    for i, r in want.items():
        assert zk.reason_at(i, n)[0] == r, i
    assert "validAt" in zk.reason_at(n - 1, n)[1] and "sample_rate" in zk.reason_at(n - 2, n)[1]
    with pytest.raises(Reject) as e:
        zk.compare(["1"] * 3, ["1"] * 4)
    assert e.value.reason == "proof_invalid"


# -- public vector vs the spike's prep_popt2 (read-only)

def _fx(name):
    return json.loads((FIX / f"{name}.json").read_text())


def _fieldtest_code(seed: str, role: str, sr: int) -> tuple[bytes, bytes]:
    key = hashlib.sha256(f"fieldtest-v1|{seed}|JBL250|{role}|bed".encode()).digest()
    cI, cQ = popt2.code_from_template(jbl250.template(key, role, sr), sr)
    return cI.tobytes(), cQ.tobytes()


def _fixture_vector(fx, role, issuer=DEV_ISSUER, valid_at=VALID_AT, salt=None):
    ro = fx["roles"][role]
    t = decode_transcript(b64d(ro["transcript_b64"]))
    sr, other = ro["sample_rate"], "B" if role == "A" else "A"
    salt = int(ro["salt_dev"], 16) if salt is None else salt
    return zk.public_vector(t, _fieldtest_code(fx["seed_hex"], role, sr), _fieldtest_code(fx["seed_hex"], other, sr),
                            issuer, valid_at, salt)


@need_spike
@pytest.mark.parametrize("name,role", [("180ca04b_48k", "A"), ("180ca04b_48k", "B"), ("180ca04b_mix", "B"),
                                       ("b550cf12_mix", "A")])
def test_public_vector_matches_spike(name, role):
    f = INPUTS / f"popt2_{name}_{role}.public.json"
    if not f.exists():
        pytest.skip("spike inputs not built")
    want = json.loads(f.read_text())["public"]
    got = _fixture_vector(_fx(name), role)
    assert len(got) == zk.n_public(popt2.RATES[_fx(name)["roles"][role]["sample_rate"]]["L"])
    assert got == want


# -- the real verifier (app/prover host build) on a real proof

def _real_verifier(**kw):
    return zk.Verifier(str(BIN), str(VK_DIR), f"{HEAVY} zk-verify-test" if HEAVY.exists() else None, **kw)


@pytest.fixture(scope="module")
def real():
    return _real_verifier(), PROOF.read_bytes() if PROOF.exists() else b"", _fx("180ca04b_48k") if FIX.is_dir() else {}


@need_real
def test_real_proof_accepted(real):
    v, proof, fx = real
    v.verify("oa2t_s48", proof, _fixture_vector(fx, "A"))


@need_real
def test_real_proof_wrong_public_input(real):
    """Another salt -> another halfCommit (index 0); another validAt -> the last input."""
    v, proof, fx = real
    with pytest.raises(Reject) as e:
        v.verify("oa2t_s48", proof, _fixture_vector(fx, "A", salt=int(fx["roles"]["A"]["salt_dev"], 16) + 1))
    assert e.value.reason == "transcript_mismatch" and "public[0]" in e.value.detail
    with pytest.raises(Reject) as e:
        v.verify("oa2t_s48", proof, _fixture_vector(fx, "A", valid_at=VALID_AT + 1))
    assert e.value.reason == "transcript_mismatch" and "validAt" in e.value.detail


@need_real
def test_real_proof_wrong_issuer(real):
    v, proof, fx = real
    other = pub_bytes(ec.generate_private_key(ec.SECP256R1()).public_key())
    with pytest.raises(Reject) as e:
        v.verify("oa2t_s48", proof, _fixture_vector(fx, "A", issuer=other))
    assert e.value.reason == "issuer_unknown"


@need_real
def test_real_proof_garbage_and_pins(real):
    v, proof, fx = real
    want = _fixture_vector(fx, "A")
    with pytest.raises(Reject) as e:
        v.verify("oa2t_s48", proof[:-1000] + bytes(1000), want)
    assert e.value.reason == "proof_invalid"
    with pytest.raises(Reject) as e:
        _real_verifier(pins={"oa2t_s48": "00" * 32}).verify("oa2t_s48", proof, want)
    assert e.value.reason == "circuit_unknown"


def test_verifier_unavailable(tmp_path):
    v = zk.Verifier(None, str(tmp_path))
    assert not v.available("oa2t_s48")
    with pytest.raises(zk.Unavailable):
        v.verify("oa2t_s48", b"x", ["0"])
    with pytest.raises(Reject) as e:
        v.verify("oa2t_pair", b"x", ["0"])
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


HOLD = "%064x" % poseidon7.sponge16(poseidon7.TAG_HOLD, [123456789])


@pytest.fixture
def zk_world(clock, tmp_path):
    def make(d=30, holder=True, v1=(), verifier=None, **cfg):
        cfg.setdefault("issuer_key_file", str(tmp_path / "issuer.pem"))
        fv = verifier or FakeVerifier()
        app = create_app(Settings(db=":memory:", allow_unattested=True, now_ms=clock, data_dir=str(tmp_path), **cfg),
                         SqliteStore(":memory:"), verifier=fv)
        w = World2(TestClient(app), clock, d, Knobs(),
                   Knobs(sr=44100, mono_off_ns=9_000_000_000, sync_err_ms=-3, out_lat_ms=25), v1=v1, real_root=False)
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
    r = _upload(w.a, w.sid, b"x", {"attempt": 0, "circuit": "oa2t_s48", "salt": "1"})
    assert r.status_code == 409 and r.json()["error"] == "bad_state"
    assert w.fv.calls == 0


def test_proof_verified_both_roles(zk_world):
    w = zk_world()
    _near(w)
    rec = w.result().json()
    t0 = rec["t0_ms"]
    assert rec["zk"] == {"valid_at": t0 // 1000, "status": "none", "A": None, "B": None}
    assert w.view()["zk_valid_at"] == t0 // 1000
    r = _send(w, w.a)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "verified" and j["zk"]["status"] == "partial" and j["zk"]["A"]["circuit"] == "oa2t_s48"
    assert "salt" not in j["zk"]["A"] and j["zk"]["A"]["half_commit"] == _vector(w, w.a)[0]
    assert (w.tmp / "sessions" / w.sid / "proof_A_0.bin").exists()
    r = _send(w, w.b, salt=99)                                    # B is at 44.1 kHz
    assert r.status_code == 200, r.text
    rec = w.result().json()
    assert rec["zk"]["status"] == "verified" and rec["zk"]["B"]["circuit"] == "oa2t_s44"
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
    r = _upload(w.b, w.sid, proof, {"attempt": 0, "circuit": "oa2t_s44", "salt": "6"})   # proof made with salt 5
    assert r.status_code == 400 and r.json()["error"] == "transcript_mismatch" and "public[0]" in r.json()["detail"]
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
    for meta in ({"attempt": 0, "circuit": "oa2t_s48"}, {"attempt": 0, "circuit": "oa2t_s48", "salt": "0x" + "f" * 63},
                 {"attempt": 0, "circuit": "oa2t_s48", "salt": "abc"}):
        r = _upload(w.a, w.sid, good, meta)
        assert r.status_code == 400 and r.json()["error"] == "bad_request", meta
    r = _upload(w.a, w.sid, good, {"attempt": 1, "circuit": "oa2t_s48", "salt": "7"})
    assert r.status_code == 400 and r.json()["error"] == "bad_attempt"
    r = _upload(w.a, w.sid, b"", {"attempt": 0, "circuit": "oa2t_s48", "salt": "7"})
    assert r.status_code == 400
    r = _upload(w.a, w.sid, b"not json", {"attempt": 0, "circuit": "oa2t_s48", "salt": "7"})
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
    w = zk_world(verifier=zk.Verifier(None, str(tmp_path)))
    _near(w)
    r = _send(w, w.a)
    assert r.status_code == 503 and r.json()["error"] == "zk_unavailable"
    assert w.result().json()["zk"]["A"] is None
    cfg = w.a.client.get("/v1/config").json()["zk"]
    assert cfg["verifier"] == {"oa2t_s48": False, "oa2t_s44": False} and cfg["circuits"]["48000"] == "oa2t_s48"


# -- proving-key download

def test_key_download(make_client, tmp_path):
    kd = tmp_path / "keys"
    kd.mkdir()
    data = os.urandom(300_000)
    (kd / "oa2t_s48.pk.zst").write_bytes(data)
    (kd / "oa2t_s48.pk").write_bytes(b"raw")                     # not served
    c = make_client(zk_keys=str(kd))
    sha = hashlib.sha256(data).hexdigest()
    m = c.get("/v1/zk/keys").json()["keys"]
    assert m == [{"circuit": "oa2t_s48", "sample_rate": 48000, "file": "oa2t_s48.pk.zst",
                  "url": "/v1/zk/keys/oa2t_s48.pk.zst", "size": len(data), "sha256": sha,
                  "vk_sha256": zk.VK_PINS["oa2t_s48"]}]
    r = c.get("/v1/zk/keys/oa2t_s48.pk.zst")
    assert r.status_code == 200 and r.content == data and r.headers["x-pop-sha256"] == sha
    assert r.headers.get("accept-ranges") == "bytes"
    r = c.get("/v1/zk/keys/oa2t_s48.pk.zst", headers={"Range": "bytes=100000-"})
    assert r.status_code == 206 and r.content == data[100000:]
    assert r.headers["content-range"] == f"bytes 100000-{len(data) - 1}/{len(data)}"
    r = c.get("/v1/zk/keys/oa2t_s48.pk.zst", headers={"Range": f"bytes={len(data)}-"})
    assert r.status_code == 416
    for name in ("oa2t_s44.pk.zst", "oa2t_s48.pk", "..%2Fissuer.pem", "oa2t_pair.pk.zst"):
        assert c.get(f"/v1/zk/keys/{name}").status_code == 404, name
    assert c.get("/v1/config").json()["zk"]["keys"] == "/v1/zk/keys"
