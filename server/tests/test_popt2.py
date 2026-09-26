"""POPT v2 / POPC v2 layout, Poseidon7 + rec_root, int8 codes, code_commit and exact decide.

Literal vectors run everywhere. Spike parity (research/sound-bound/spikes/zk, read-only; skipped when absent):
every fixtures/popt_v2 session (12 JBL250 sessions x {48k, mix} + sodfar/sodwide): transcript + commit bytes,
signatures, derived fields, code_commit from the server's own code derivation, rec_root from the dumped tree
leaves, sampled leaves re-hashed from the capture, and full rec_root recomputed for two captures
(POP_SLOW=1: every capture, ~2.5 s each).
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from pop import constants as K
from pop import poseidon7 as p7
from pop import popt2
from pop.codec import decode_commit, decode_transcript, encode_commit, encode_transcript
from pop.crypto import verify_raw
from pop.jbl250 import template
from pop.verdict import Reject, check_commit, check_transcript, combine, decide, flight_cm, flight_exact, self_os_ok

ZK = Path(__file__).resolve().parents[2] / "research" / "sound-bound" / "spikes" / "zk"
FIX = ZK / "fixtures" / "popt_v2"
need_spike = pytest.mark.skipif(not FIX.is_dir(), reason="research/ spike not present")
FIXTURES = sorted(FIX.glob("*.json")) if FIX.is_dir() else []
SLOW = os.environ.get("POP_SLOW") == "1"

VEC2 = dict(version=2, role="B", attempt=1, nonce=bytes(range(32)), pk_self=b"\x04" + b"\x11" * 64,
            pk_partner=b"\x04" + b"\x22" * 64, sample_rate=44100, half=-45566, rec_root=b"\x33" * 32,
            play_frame_position=26400, play_nano_time=123456789012345, rec_frame0_nano_time=123456000000000,
            self_os_delta=-7, commit_hash=b"\x44" * 32, a_self=69253, p_partner=27958, delta=88,
            code_commit=b"\x55" * 32)
VEC2_SHA = "77c8f8f8755d2767e41618c5fd009084854d8321932fe4c2eb372f6c313a1f71"
COMMIT2_SHA = "e8a0dc9bfb77e580677d6f110250db7ee07e0b24880a1e9b9e446685bf467a1d"   # ("B", 1, range(32), 0x33*32)


def _spike(mod: str, sub: str):
    sys.dont_write_bytecode = True
    p = str(ZK / sub)
    if p not in sys.path:
        sys.path.insert(0, p)
    return __import__(mod)


# -- layout

def test_v2_vector_and_offsets():
    raw = encode_transcript(VEC2)
    assert len(raw) == 311 and hashlib.sha256(raw).hexdigest() == VEC2_SHA
    assert raw[:7] == b"POPT\x02B\x01" and raw[177:209] == b"\x33" * 32 and raw[237:269] == b"\x44" * 32
    assert struct.unpack(">IIH", raw[269:279]) == (69253, 27958, 88) and raw[279:311] == b"\x55" * 32
    t = decode_transcript(raw)
    assert {k: t[k] for k in VEC2} == VEC2
    assert t["p_self"] == 69260 and t["a_partner"] == 69253 + 45566      # B: a_partner = a_self - half


def test_v2_commit_vector():
    c = encode_commit("B", 1, bytes(range(32)), b"\x33" * 32, version=2)
    assert len(c) == 71 and c[:7] == b"POPC\x02B\x01" and hashlib.sha256(c).hexdigest() == COMMIT2_SHA
    d = decode_commit(c)
    assert d["version"] == 2 and d["rec_root"] == b"\x33" * 32 and "rec_sha256" not in d


@pytest.mark.parametrize("mut", [
    lambda r: r[:-1], lambda r: r + b"\0", lambda r: r[:4] + b"\x01" + r[5:],       # 311 bytes must be v2
    lambda r: r[:269], lambda r: r[:4] + b"\x01" + r[5:269] + b"\0" * 42,
    lambda r: r[:5] + b"C" + r[6:], lambda r: r[:177] + p7.P.to_bytes(32, "big") + r[209:]])
def test_v2_decode_rejects(mut):
    with pytest.raises(ValueError):
        decode_transcript(mut(encode_transcript(VEC2)))


def test_v1_269_with_version2_rejected():
    raw = bytearray(encode_transcript(VEC2)[:269])
    with pytest.raises(ValueError):
        decode_transcript(bytes(raw))


def test_commit_root_canonical():
    with pytest.raises(ValueError):
        decode_commit(encode_commit("A", 0, bytes(32), p7.P.to_bytes(32, "big"), version=2))
    assert decode_commit(encode_commit("A", 0, bytes(32), (p7.P - 1).to_bytes(32, "big"), version=2))
    assert decode_commit(encode_commit("A", 0, bytes(32), b"\xff" * 32))["rec_sha256"] == b"\xff" * 32   # v1: any


@need_spike
def test_codec_matches_spike_popt():
    popt = _spike("popt", "enclave")
    raw = encode_transcript(VEC2)
    t = {("rec" if k == "rec_root" else k): v for k, v in VEC2.items() if k != "version"}
    assert popt.encode(t, 2) == raw and popt.popc(2, "B", 1, bytes(range(32)), b"\x33" * 32) == \
        encode_commit("B", 1, bytes(range(32)), b"\x33" * 32, version=2)
    d = popt.decode(raw)
    ours = decode_transcript(raw)
    assert (d["p_self"], d["a_partner"]) == (ours["p_self"], ours["a_partner"])


# -- Poseidon7 / rec_root (docs/pop-transcript-v2.md §2; port spec §2.4 vectors)

H = lambda s: int(s, 16)   # noqa: E731


def test_poseidon7_vectors():
    assert p7.perm([0, 1, 2, 3, 4]) == [
        H("b53441b5947859ddb7a6938ab257200f5432e5488686b00d025faf664b202dcb"),
        H("6f764805acb9ba37b7270db8b95724c398bbf95e9931e2d66edd6fee9b61d6a3"),
        H("15f05c32fa3f1cb59120c3bee86434d193df0c50e82cefa92bac1cb81231b9ef"),
        H("bc12f35ab40af82e83a3b85fa83b87642fd2ee9549f97eb8817edb8754323750"),
        H("4e63ae3fac36a3c827b999341793790111f8162acf77074eb53743b899632f04")]
    assert p7.perm(list(range(16)))[:3] == [H("dcba093ac6c0725e07cc6aedaf7499c26398e70256aa80160a062c3acdd8f99c"),
                                             H("07949afe41b271d0ddb20e8abcd66dfae82af3271c3ede21448c1e3b34f6ce3a"),
                                             H("3a8bd1602964f4e54eb843184a6576f3e5f96fa04a6d2f41503226dc8bcee684")]
    assert p7.node5([1, 2, 3, 4]) == H("678179d0d4dc0eec9d951542cd484b1a1b3f846cdd7a9f939143b57ae7366039")
    assert p7.sponge16(6, [1]) == H("892b94c43e27b362a254ccbfe2480510cc7a2930e0dc8ea82d69f4b8e1e94714")
    assert p7.sponge16(5, [1, 2, 3]) == H("f0fefa4bd16800a07f89c9f60771a0207a828c3d3e721bdf8dd8101dd87752a8")
    assert p7.sponge16(8, list(range(1, 10))) == H("155a502f4baf3a57d8dc33a6874c793fa4c546e7596caaa47ac6be54ed6c98ff")


def test_leaf_and_root_vectors():
    z = p7.pack_leaf([0] * 1024)
    assert len(z) == 69 and z[0] == H("8000" * 15) and z[68] == H("8000" * 4)
    x = [(37 * i % 65536) - 32768 for i in range(1024)]
    want = H("ef0a5688afd393e3b1f9e8540f5f8e87ab0ae57cb3e03049da0a50e1e20a03f7")
    assert p7.leaf_hash(x) == want and p7.leaf_hashes(np.array(x)) == [want]
    assert p7.zero_nodes()[0] == H("4fb08dbbdd4688b1ebb14e33eeedaaa58973eab300e6ed8f42b233448a0a0277")
    assert p7.zero_nodes()[4] == H("84bbbe7dc7801e2f95afea4bb04db044d53bbfd09962b9a5473061626f3f3b3b")
    y = np.array([(7919 * i % 65536) - 32768 for i in range(3000)])
    assert p7.rec_root(y).hex() == "5504788da1382ecb8dc674884b63b80173cd383be221bb881f0c59e91ed449cf"
    # zero-padding is zero SAMPLES: a capture of 1,024 zeros has the all-zero root
    assert p7.rec_root(np.zeros(1024, dtype=np.int16)) == p7.zero_nodes()[4].to_bytes(32, "big")


def test_lockstep_equals_scalar():
    rng = np.random.default_rng(1)
    x = rng.integers(-32768, 32768, 3 * 1024 + 17)
    padded = np.concatenate([x, np.zeros(4 * 1024 - x.size, dtype=x.dtype)])
    assert p7.leaf_hashes(x) == [p7.leaf_hash(padded[i * 1024:(i + 1) * 1024].tolist()) for i in range(4)]
    with pytest.raises(ValueError):
        p7.leaf_hashes(np.array([40000]))


@need_spike
def test_poseidon7_matches_spike():
    sp = _spike("p7", "optionA-v2/poseidon7")
    rng = np.random.default_rng(2)
    for t in (5, 16):
        s = [int.from_bytes(rng.bytes(32), "big") % p7.P for _ in range(t)]
        assert p7.perm(s) == sp.perm(s)
    xs = [int.from_bytes(rng.bytes(31), "big") for _ in range(20)]
    assert p7.sponge16(9 + (40 << 8), xs) == sp.sponge16(9 + (40 << 8), xs)


# -- codes

def test_code_shape_and_commit():
    key = hashlib.sha256(b"k").digest()
    for sr in (48000, 44100, 96000):
        cI, cQ = popt2.code(key, "A", sr)
        assert len(cI) == len(cQ) == round(0.25 * sr)
        a = np.frombuffer(cI + cQ, dtype=np.int8)
        assert a.min() >= -127 and a.max() <= 127 and max(abs(a.min()), a.max()) == 127
    own, other = popt2.code(key, "A", 48000), popt2.code(hashlib.sha256(b"k2").digest(), "B", 48000)
    assert popt2.code_commit(own, other) == hashlib.sha256(b"pop-code-v2" + own[0] + own[1] + other[0] + other[1]).digest()
    assert popt2.code_commit(own, other) != popt2.code_commit(other, own)
    assert popt2.delta(48000) == 96 and popt2.delta(44100) == 88


@need_spike
def test_rates_table_matches_spike():
    pytest.importorskip("scipy")
    oa = _spike("oa_rate", "optionA-v2")
    for sr, v in popt2.RATES.items():
        p = oa.params(sr)
        assert (p["L"], p["B"], p["DELTA"], p["WPRE"], p["WPOST"], p["h"]) == \
            (v["L"], v["B"], v["delta"], v["wpre"], v["wpost"], v["h"])


# -- exact decide (oa2t_pair: c*N <= -40*S impossible, c*N >= 120*S too far)

def _circuit(ha, sra, hb, srb):
    n, s = ha * srb - hb * sra, sra * srb
    if K.SPEED_OF_SOUND_CM_S * n <= -40 * s:
        return None, "impossible_flight"
    if K.SPEED_OF_SOUND_CM_S * n >= 120 * s:
        return "NOT_NEAR", "too_far"
    return "NEAR", None


@pytest.mark.parametrize("ha,hb,f,out", [
    (240, 0, 60, ("NOT_NEAR", "too_far")), (239, 0, Fraction(239, 4), ("NEAR", None)),
    (-80, 0, -20, (None, "impossible_flight")), (-79, 0, Fraction(-79, 4), ("NEAR", None)),
    (45240, 45000, 60, ("NOT_NEAR", "too_far")), (45000, 45080, -20, (None, "impossible_flight"))])
def test_exact_ties_68600(ha, hb, f, out):
    """At 68.6 kHz one frame is exactly 1/4 cm, so -20 and 60 cm are reachable."""
    assert flight_exact(ha, 68600, hb, 68600) == f
    assert decide(flight_exact(ha, 68600, hb, 68600)) == out == _circuit(ha, 68600, hb, 68600)


def test_exact_matches_circuit_random():
    rng = np.random.default_rng(5)
    rates = [36000, 44100, 48000, 68600, 96000, 42875]
    for _ in range(3000):
        sra, srb = (int(v) for v in rng.choice(rates, 2))
        ha, hb = (int(v) for v in rng.integers(40000, 50000, 2))
        assert decide(flight_exact(ha, sra, hb, srb)) == _circuit(ha, sra, hb, srb)
    # float flight at a tie can land either side; the exact one can't
    f = flight_cm(240, 68600, 0, 68600)
    assert decide(flight_exact(240, 68600, 0, 68600)) == ("NOT_NEAR", "too_far") and abs(f - 60) < 1e-9


def test_self_os_exact():
    assert self_os_ok(2205, 44100) and not self_os_ok(2206, 44100) and self_os_ok(-2205, 44100)
    assert self_os_ok(2400, 48000) and not self_os_ok(-2401, 48000)
    assert K.SELF_OS_TOL_MS == 50


def test_config_exposes_v2(client):
    c = client.get("/v1/config").json()
    assert c["self_os_tol_ms"] == 50 and c["delta_ms"] == 2 and c["popt_versions"] == [1, 2]
    assert c["zk_rates"] == [44100, 48000] and c["popt2_rates"]["48000"]["B"] == 4474747
    assert c["leaf"] == 1024 and c["tree_depth"] == 4 and c["template_bits"] == 8 and c["fir_taps"] == 63


# -- spike fixtures: 12 JBL250 sessions x {48k, mix} (+ sodfar, sodwide)

def _fieldtest_code(seed: str, role: str, sr: int):
    """The spike's templates come from the fieldtest bed key; same math as production (pop-v1 bed key)."""
    key = hashlib.sha256(f"fieldtest-v1|{seed}|JBL250|{role}|bed".encode()).digest()
    return popt2.code_from_template(template(key, role, sr), sr)


def _checked(fx: dict, r: str) -> dict:
    other = "B" if r == "A" else "A"
    ro, rp = fx["roles"][r], fx["roles"][other]
    sr = int(ro["sample_rate"])
    raw, sig = (__import__("base64").b64decode(ro[k]) for k in ("transcript_b64", "sig_b64"))
    craw, csig = (__import__("base64").b64decode(ro[k]) for k in ("commit_b64", "commit_sig_b64"))
    pk, pkp, nonce = bytes.fromhex(ro["pubkey"]), bytes.fromhex(rp["pubkey"]), bytes.fromhex(fx["session_nonce"])
    c = check_commit(craw, csig, role=r, pk=pk, nonce=nonce, attempt=fx["attempt"])
    own = tuple(v.tobytes() for v in _fieldtest_code(fx["seed_hex"], r, sr))
    par = tuple(v.tobytes() for v in _fieldtest_code(fx["seed_hex"], other, sr))
    cc = popt2.code_commit(own, par)
    assert cc.hex() == ro["code_commit"]
    t = check_transcript(raw, sig, role=r, pk_self=pk, pk_partner=pkp, nonce=nonce, attempt=fx["attempt"],
                         commit_sha256=hashlib.sha256(craw).digest(), rec=c["rec_root"], sample_rate=sr,
                         version=2, code_commit=cc)
    assert encode_transcript(t) == raw and len(raw) == 311 and verify_raw(pk, raw, sig)
    for k in ("half", "a_self", "a_partner", "p_self", "p_partner", "self_os_delta", "delta"):
        assert t[k] == int(ro[k]), k
    assert int.from_bytes(t["rec_root"], "big") == int(ro["rec_root"], 16)
    with pytest.raises(Reject, match="code_commit"):
        check_transcript(raw, sig, role=r, pk_self=pk, pk_partner=pkp, nonce=nonce, attempt=fx["attempt"],
                         commit_sha256=hashlib.sha256(craw).digest(), rec=c["rec_root"], sample_rate=sr,
                         version=2, code_commit=popt2.code_commit(par, own))
    with pytest.raises(Reject, match="version"):
        check_transcript(raw, sig, role=r, pk_self=pk, pk_partner=pkp, nonce=nonce, attempt=fx["attempt"],
                         commit_sha256=hashlib.sha256(craw).digest(), rec=c["rec_root"], version=1)
    return t


@need_spike
@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_transcripts_and_verdict(path):
    fx = json.loads(path.read_text())
    ta, tb = _checked(fx, "A"), _checked(fx, "B")
    out = combine(ta, tb)
    want = fx["expect"]
    if want["verdict"] is None or want.get("reason") == "self_timestamp_mismatch":
        assert out["reason"] == want["reason"]
    else:
        assert (out["verdict"], out["reason"]) == (want["verdict"], want["reason"])
        assert out["flight_cm"] == pytest.approx(want["flight_cm"], abs=0.01)


def _captures():
    out = []
    for f in FIXTURES:
        fx = json.loads(f.read_text())
        for r in "AB":
            ro = fx["roles"][r]
            out.append(pytest.param(f.stem, r, ZK / ro["capture_npy"], ZK / ro["tree_json"], ro["rec_root"],
                                    id=f"{f.stem}-{r}"))
    return out


@need_spike
@pytest.mark.parametrize("name,role,npy,tree,root", _captures())
def test_fixture_rec_root(name, role, npy, tree, root):
    if not (npy.exists() and tree.exists()):
        pytest.skip("spike build/popt2 captures absent (gitignored there)")
    x = np.load(npy)
    assert x.dtype == np.int16 and x.size in (120000, 110250)
    d = json.loads(tree.read_text())
    assert d["depth"] == p7.DEPTH
    levels = [{int(k): int(v, 16) for k, v in lvl.items()} for lvl in d["levels"]]
    leaves = [levels[0][i] for i in range(len(levels[0]))]
    assert len(leaves) == -(-x.size // 1024)
    ours = p7.levels_from_leaves(leaves)
    assert ours == levels and p7.root_of(ours) == int(root, 16)
    full = SLOW or (name, role) in (("180ca04b_48k", "A"), ("180ca04b_mix", "B"))
    if full:
        assert p7.rec_root(x).hex() == "%064x" % int(root, 16)
    else:
        idx = [0, len(leaves) // 2, len(leaves) - 1]     # includes the zero-padded last leaf
        got = p7.leaf_hashes(np.concatenate([x[i * 1024:(i + 1) * 1024] for i in idx[:-1]] + [x[idx[-1] * 1024:]]))
        assert got == [leaves[i] for i in idx]


@need_spike
@pytest.mark.parametrize("name", ["180ca04b_48k", "180ca04b_mix"])
def test_twin_with_server_codes_finds_fixture_arrivals(name):
    """tests/twin2 (the app's integer rule) + server-derived codes reproduce the signed a_self / a_partner."""
    from tests import twin2
    fx = json.loads((FIX / f"{name}.json").read_text())
    for r in "AB":
        ro = fx["roles"][r]
        npy = ZK / ro["capture_npy"]
        if not npy.exists():
            pytest.skip("spike captures absent")
        sr, x = int(ro["sample_rate"]), np.load(npy)
        own = _fieldtest_code(fx["seed_hex"], r, sr)
        par = _fieldtest_code(fx["seed_hex"], "B" if r == "A" else "A", sr)
        assert twin2.earliest(x, own[0], own[1], *ro["search_self"], sr)[0] == int(ro["a_self"])
        assert twin2.earliest(x, par[0], par[1], *ro["search_partner"], sr)[0] == int(ro["a_partner"])
