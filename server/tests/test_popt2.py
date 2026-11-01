"""POPT v2 / POPC v2 layout, Poseidon7 (legacy) + rec_root, int8 codes, code_commit and exact decide.

Literal vectors run everywhere. One codec check against the spike's enclave/popt.py
(research/sound-bound/spikes/zk, read-only; skipped when absent).
"""
from __future__ import annotations

import hashlib
import struct
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from pop import constants as K
from pop import poseidon2 as p2
from pop import poseidon7 as p7
from pop import popt2
from pop.codec import decode_commit, decode_transcript, encode_commit, encode_transcript
from pop.verdict import decide, flight_cm, flight_exact, self_os_ok

ZK = Path(__file__).resolve().parents[2] / "research" / "sound-bound" / "spikes" / "zk"
FIX = ZK / "fixtures" / "popt_v2"
need_spike = pytest.mark.skipif(not FIX.is_dir(), reason="research/ spike not present")

VEC2 = dict(version=2, role="B", attempt=1, nonce=bytes(range(32)), pk_self=b"\x04" + b"\x11" * 64,
            pk_partner=b"\x04" + b"\x22" * 64, sample_rate=44100, half=-45566, rec_root=b"\x23" * 32,
            play_frame_position=26400, play_nano_time=123456789012345, rec_frame0_nano_time=123456000000000,
            self_os_delta=-7, commit_hash=b"\x44" * 32, a_self=69253, p_partner=27958, delta=88,
            code_commit=b"\x55" * 32)
VEC2_SHA = "77cb6f5d1bac26f7e474e1a210b9051675154e1f6b3dd2eae204582eb54c3376"
COMMIT2_SHA = "934498aab52fb4601d7ee42f0ea304cb8c31bf76b3558b33afe44d8295f0cfcc"   # ("B", 1, range(32), 0x23*32)


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
    assert raw[:7] == b"POPT\x02B\x01" and raw[177:209] == b"\x23" * 32 and raw[237:269] == b"\x44" * 32
    assert struct.unpack(">IIH", raw[269:279]) == (69253, 27958, 88) and raw[279:311] == b"\x55" * 32
    t = decode_transcript(raw)
    assert {k: t[k] for k in VEC2} == VEC2
    assert t["p_self"] == 69260 and t["a_partner"] == 69253 + 45566      # B: a_partner = a_self - half


def test_v2_commit_vector():
    c = encode_commit("B", 1, bytes(range(32)), b"\x23" * 32, version=2)
    assert len(c) == 71 and c[:7] == b"POPC\x02B\x01" and hashlib.sha256(c).hexdigest() == COMMIT2_SHA
    d = decode_commit(c)
    assert d["version"] == 2 and d["rec_root"] == b"\x23" * 32 and "rec_sha256" not in d


@pytest.mark.parametrize("mut", [
    lambda r: r[:-1], lambda r: r + b"\0", lambda r: r[:4] + b"\x01" + r[5:],       # 311 bytes must be v2
    lambda r: r[:269], lambda r: r[:4] + b"\x01" + r[5:269] + b"\0" * 42,
    lambda r: r[:5] + b"C" + r[6:], lambda r: r[:177] + p2.R.to_bytes(32, "big") + r[209:]])
def test_v2_decode_rejects(mut):
    with pytest.raises(ValueError):
        decode_transcript(mut(encode_transcript(VEC2)))


def test_v1_269_with_version2_rejected():
    raw = bytearray(encode_transcript(VEC2)[:269])
    with pytest.raises(ValueError):
        decode_transcript(bytes(raw))


def test_commit_root_canonical():
    with pytest.raises(ValueError):
        decode_commit(encode_commit("A", 0, bytes(32), p2.R.to_bytes(32, "big"), version=2))
    assert decode_commit(encode_commit("A", 0, bytes(32), (p2.R - 1).to_bytes(32, "big"), version=2))
    assert decode_commit(encode_commit("A", 0, bytes(32), b"\xff" * 32))["rec_sha256"] == b"\xff" * 32   # v1: any


@need_spike
def test_codec_matches_spike_popt():
    popt = _spike("popt", "enclave")
    raw = encode_transcript(VEC2)
    t = {("rec" if k == "rec_root" else k): v for k, v in VEC2.items() if k != "version"}
    assert popt.encode(t, 2) == raw and popt.popc(2, "B", 1, bytes(range(32)), b"\x23" * 32) == \
        encode_commit("B", 1, bytes(range(32)), b"\x23" * 32, version=2)
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


# -- codes

def test_code_shape_and_commit():
    key = hashlib.sha256(b"k").digest()
    for sr in (48000, 44100, 96000):
        cI, cQ = popt2.code(key, "A", sr)
        assert len(cI) == len(cQ) == round(0.25 * sr)
        a = np.frombuffer(cI + cQ, dtype=np.int8)
        assert a.min() >= -127 and a.max() <= 127 and max(abs(a.min()), a.max()) == 127
    own, other = popt2.code(key, "A", 48000), popt2.code(hashlib.sha256(b"k2").digest(), "B", 48000)
    i8 = lambda b: np.frombuffer(b, dtype=np.int8).tolist()   # noqa: E731
    assert popt2.code_commit(own, other) == p2.to_bytes32(p2.code_commitment(*map(i8, (*own, *other))))
    assert popt2.code_commit(own, other) != popt2.code_commit(other, own)
    assert popt2.delta(48000) == 96 and popt2.delta(44100) == 88


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
