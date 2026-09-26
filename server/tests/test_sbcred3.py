"""SBcred3 issuance vs the optionA-v2 spike (fixtures, dev issuer, popzk), read-only imports from research/.

POP_ZK_CHECK=1 also runs the real circuit (oa2zk check, ~1 min, under tools/heavy.sh) on a spike witness whose
credential is re-issued by this server: accepted with our issuer, refused when expired or under another issuer.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from pop import issuer as sbcred
from pop.crypto import device_id, pub_bytes, sign_raw, verify_raw
from tests.phones import Phone, make_chain

ZK = Path(__file__).resolve().parents[2] / "research" / "sound-bound" / "spikes" / "zk"
FIX = ZK / "fixtures" / "popt_v2"
DEV_PEM = ZK / "enclave" / "keys" / "issuer_dev.pem"
OA2 = ZK / "optionA-v2"
need_spike = pytest.mark.skipif(not (FIX.is_dir() and DEV_PEM.exists()), reason="research/ spike not present")


def _popzk():
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ZK / "verifier"))
    import popzk
    return popzk


def _fixtures():
    return sorted(FIX.glob("*.json")) if FIX.is_dir() else []


def _enroll(client, pub65: bytes, holder: str | None, name="Cred"):
    n = client.get("/v1/enroll/nonce").json()["nonce"]
    body = {"nonce": n, "device_id": device_id(pub65), "pubkey": pub65.hex(), "display_name": name, "chain": None}
    if holder is not None:
        body["holder_commit"] = holder
    return client.post("/v1/enroll", json=body)


# -- layout / signature vs the spike fixtures

@need_spike
@pytest.mark.parametrize("path", _fixtures(), ids=lambda p: p.stem)
def test_fixture_bytes_and_sig(path):
    fx = json.loads(path.read_text())
    iss = bytes.fromhex("04" + fx["issuer"]["pub_x"] + fx["issuer"]["pub_y"])
    for r in "AB":
        ro = fx["roles"][r]
        hold = sbcred.parse_holder_commit("%064x" % int(ro["holder_commit"], 16))   # fixture hex is unpadded
        cred = sbcred.build(bytes.fromhex(ro["pubkey"]), ro["cred_expiry_unix"], hold)
        assert cred.hex() == ro["cred_hex"] and len(cred) == sbcred.CRED_LEN
        sig = bytes.fromhex(ro["cred_sig_r_hex"] + ro["cred_sig_s_hex"])
        c = sbcred.check(cred, sig, iss, 1_790_000_000)
        assert c["pub"].hex() == ro["pubkey"] and c["expiry"] == ro["cred_expiry_unix"]


@need_spike
def test_enroll_with_dev_issuer_reproduces_fixture(make_client, clock):
    """Same pub, expiry and holder_commit as the fixture -> identical 111 bytes; sig verifies under the dev issuer."""
    popzk = _popzk()
    fx = json.loads((FIX / "180ca04b_48k.json").read_text())
    ro = fx["roles"]["A"]
    client = make_client(allow_unattested=True, issuer_key_file=str(DEV_PEM))
    clock.ms = (ro["cred_expiry_unix"] - sbcred.CRED_TTL_S) * 1000 + 123
    iss = client.get("/v1/config").json()["issuer"]
    assert (iss["pub_x"], iss["pub_y"]) == popzk.DEV_ISSUER == (fx["issuer"]["pub_x"], fx["issuer"]["pub_y"])
    r = _enroll(client, bytes.fromhex(ro["pubkey"]), "%064x" % int(ro["holder_commit"], 16))
    assert r.status_code == 200, r.text
    c = r.json()["credential"]
    cred, sig = base64.b64decode(c["cred_b64"]), base64.b64decode(c["sig_b64"])
    assert cred.hex() == ro["cred_hex"] and c["expiry"] == ro["cred_expiry_unix"]
    assert verify_raw(bytes.fromhex(iss["pubkey"]), cred, sig) and c["issuer_pubkey"] == iss["pubkey"]


# -- server behaviour

def test_config_publishes_issuer(client):
    iss = client.get("/v1/config").json()["issuer"]
    assert iss["pubkey"] == client.app.state.issuer.pub.hex() and iss["pubkey"] == "04" + iss["pub_x"] + iss["pub_y"]
    assert iss["alg"] == "ES256" and iss["cred_format"] == "SBcred3" and iss["cred_ttl_s"] == sbcred.CRED_TTL_S


def test_enroll_issues_and_stores(make_client, clock):
    client = make_client(cred_ttl_s=3600)
    p = Phone(client, clock)
    hold = (12345).to_bytes(32, "big").hex()
    n = client.get("/v1/enroll/nonce").json()["nonce"]
    body = {**p.enroll_body(n, make_chain(p.sk.public_key(), bytes.fromhex(n))), "holder_commit": "0x" + hold}
    r = client.post("/v1/enroll", json=body)
    assert r.status_code == 200, r.text
    c = r.json()["credential"]
    cred, sig = base64.b64decode(c["cred_b64"]), base64.b64decode(c["sig_b64"])
    assert cred == b"SBcred3" + p.pub[1:] + (clock.ms // 1000 + 3600).to_bytes(8, "big") + bytes.fromhex(hold)
    assert c["expiry"] == clock.ms // 1000 + 3600 and len(sig) == 64
    sbcred.check(cred, sig, client.app.state.issuer.pub, clock.ms // 1000)
    d = client.app.state.store.get_device(p.device_id)
    assert (d["cred"], d["cred_sig"], d["cred_expiry"], d["holder_commit"]) == (cred.hex(), sig.hex(), c["expiry"], hold)


def test_v1_enroll_without_holder_commit(client, clock):
    p = Phone(client, clock)
    r = p.enroll()
    assert r.status_code == 200 and "credential" not in r.json()
    assert client.app.state.store.get_device(p.device_id)["cred"] is None


@pytest.mark.parametrize("hold", [
    "%064x" % sbcred.P256_P, "ff" * 32, "00" * 31, "00" * 33, "zz" * 32, "",
])
def test_bad_holder_commit(make_client, hold):
    client = make_client(allow_unattested=True)
    r = _enroll(client, pub_bytes(ec.generate_private_key(ec.SECP256R1()).public_key()), hold)
    assert r.status_code == 400 and r.json()["error"] == "bad_holder_commit"


def test_holder_commit_p_minus_1_ok(make_client):
    client = make_client(allow_unattested=True)
    r = _enroll(client, pub_bytes(ec.generate_private_key(ec.SECP256R1()).public_key()), "%064x" % (sbcred.P256_P - 1))
    assert r.status_code == 200 and "credential" in r.json()


def test_expired_and_foreign(client, clock):
    iss = client.app.state.issuer
    pub = pub_bytes(ec.generate_private_key(ec.SECP256R1()).public_key())
    c = iss.issue(pub, b"\x01" * 32, 1_000)
    sbcred.check(c["cred"], c["sig"], iss.pub, c["expiry"])          # validAt == expiry is still valid (<=)
    with pytest.raises(sbcred.CredError) as e:
        sbcred.check(c["cred"], c["sig"], iss.pub, c["expiry"] + 1)
    assert e.value.code == "credential_expired"
    other = ec.generate_private_key(ec.SECP256R1())
    forged = sign_raw(other, c["cred"])
    with pytest.raises(sbcred.CredError) as e:
        sbcred.check(c["cred"], forged, iss.pub, 1_000)
    assert e.value.code == "issuer_unknown"


# -- key loading

def test_key_from_env_hex_and_pem(tmp_path):
    sk = ec.generate_private_key(ec.SECP256R1())
    hx = "%064x" % sk.private_numbers().private_value
    assert sbcred.Issuer(sbcred.load_key(hx, tmp_path / "none.pem")).pub == pub_bytes(sk.public_key())
    assert not (tmp_path / "none.pem").exists()
    from cryptography.hazmat.primitives import serialization
    pem = sk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                           serialization.NoEncryption()).decode()
    assert sbcred.Issuer(sbcred.load_key(pem, tmp_path / "none.pem")).pub == pub_bytes(sk.public_key())


def test_key_file_autogen_persists(tmp_path):
    f = tmp_path / "d" / "issuer.pem"
    a = sbcred.Issuer(sbcred.load_key(None, f))
    assert f.exists() and (f.stat().st_mode & 0o777) == 0o600
    assert sbcred.Issuer(sbcred.load_key(None, f)).pub == a.pub
    with pytest.raises(FileNotFoundError):
        sbcred.load_key(None, tmp_path / "missing.pem", autogen=False)


# -- popzk session verifier (read-only import): the issuer pin and validAt

def _phone_publics(popzk, fx, role, issuer_xy, valid_at):
    session = {"nonce": fx["session_nonce"], "attempt": fx["attempt"], "code_seed_hex": fx["seed_hex"]}
    vals, _ = popzk.derive_phone_inputs(session, role, 48000, popzk.Policy(issuer=issuer_xy, valid_at=valid_at))
    return session, ["1"] + vals        # halfCommit output first


def _verify(popzk, monkeypatch, pub, session, policy):
    monkeypatch.setattr(popzk, "check_circuit", lambda c, pol, kind: popzk.CIRCUITS[c])
    monkeypatch.setattr(popzk, "inspect", lambda c, proof: pub)
    return popzk.verify_phone("A", {"circuit": "oa2t_s48", "proof": "-"}, session, policy)


@need_spike
def test_popzk_issuer_and_validat(client, monkeypatch):
    """Stand-in for a proof: its public vector (the SNARK is exercised in the POP_ZK_CHECK test below)."""
    popzk = _popzk()
    fx = json.loads((FIX / "180ca04b_48k.json").read_text())
    ours = (client.app.state.issuer.pub[1:33].hex(), client.app.state.issuer.pub[33:].hex())
    va = 1_790_000_000
    session, pub = _phone_publics(popzk, fx, "A", ours, va)
    assert _verify(popzk, monkeypatch, pub, session, popzk.Policy(issuer=ours, valid_at=va))["sr"] == 48000
    with pytest.raises(popzk.Reject) as e:          # our credential, verifier pinned to another issuer
        _verify(popzk, monkeypatch, pub, session, popzk.Policy(valid_at=va))
    assert e.value.reason == "issuer_unknown"
    # expired: the circuit forces validAt <= expiry, so a prover holding a credential that expired before the
    # verifier's validAt can only publish an older validAt
    with pytest.raises(popzk.Reject) as e:
        _verify(popzk, monkeypatch, pub, session, popzk.Policy(issuer=ours, valid_at=va + 1))
    assert e.value.reason == "transcript_mismatch" and "validAt" in e.value.detail


# -- the real circuit (opt-in)

HEAVY = ZK / "tools" / "heavy.sh"
INPUT = OA2 / "inputs" / "popt2_180ca04b_48k_A.input.json"
zk_check = pytest.mark.skipif(os.environ.get("POP_ZK_CHECK") != "1" or not INPUT.exists(),
                              reason="POP_ZK_CHECK=1 runs oa2zk check (~1 min, heavy lock)")


def _oa2zk_check(inp: dict, tmp_path: Path, tag: str) -> tuple[bool, list[str], str]:
    f = tmp_path / f"{tag}.input.json"
    f.write_text(json.dumps(inp))
    r = subprocess.run([str(HEAVY), f"sbcred3-{tag}", str(OA2 / "oa2zk.sh"), "check", "oa2t_s48", str(f)],
                       capture_output=True, text=True)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), (r.stdout + r.stderr)[-300:])
    if " ACCEPT " not in line:
        return False, [], line
    return True, line.split("public=[", 1)[1].rstrip("]").split(","), line


@zk_check
def test_circuit_accepts_server_cred_rejects_expired_and_foreign(client, tmp_path):
    popzk = _popzk()
    base = json.loads(INPUT.read_text())
    pub65 = b"\x04" + bytes(base["ownPub"])
    exp = int.from_bytes(bytes(base["exp"]), "big")
    iss = client.app.state.issuer
    cred = sbcred.build(pub65, exp, bytes(base["holdCommit"]))
    sig = sign_raw(iss.sk, cred)
    r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    n = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
    ours = {"cred_r": str(r), "cred_sInv": str(pow(s, -1, n)),
            "issuerX": str(int.from_bytes(iss.pub[1:33], "big")), "issuerY": str(int.from_bytes(iss.pub[33:], "big"))}

    ok, pub, line = _oa2zk_check({**base, **ours}, tmp_path, "ours")
    assert ok, line
    assert pub[-4:-2] == [ours["issuerX"], ours["issuerY"]] and pub[-1] == str(base["validAt"])
    fx = json.loads((FIX / "180ca04b_48k.json").read_text())
    session = {"nonce": fx["session_nonce"], "attempt": fx["attempt"], "code_seed_hex": fx["seed_hex"]}
    xy = (iss.pub[1:33].hex(), iss.pub[33:].hex())
    mp = pytest.MonkeyPatch()
    try:
        _verify(popzk, mp, pub, session, popzk.Policy(issuer=xy, valid_at=int(base["validAt"])))
        with pytest.raises(popzk.Reject) as e:
            _verify(popzk, mp, pub, session, popzk.Policy(valid_at=int(base["validAt"])))
        assert e.value.reason == "issuer_unknown"
    finally:
        mp.undo()

    ok, _, line = _oa2zk_check({**base, **ours, "validAt": str(exp + 1)}, tmp_path, "expired")
    assert not ok and "REJECT" in line, line
    ok, _, line = _oa2zk_check({**base, **ours, "issuerX": base["issuerX"], "issuerY": base["issuerY"]},
                               tmp_path, "foreign")
    assert not ok and "REJECT" in line, line
