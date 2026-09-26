import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest

from pop import constants as K
from pop import jbl250

GOLDEN = Path(__file__).resolve().parent / "golden"
FIELDTEST = Path(__file__).resolve().parents[2] / "research/sound-bound/spikes/melody/fieldtest"
SEED = "5b" * 32
CASES = [(r, sr) for r in "AB" for sr in (44100, 48000)]


def field_key(seed: str, role: str) -> bytes:
    return hashlib.sha256(f"fieldtest-v1|{seed}|JBL250|{role}|bed".encode()).digest()


@pytest.mark.parametrize("role,sr", CASES)
def test_golden(role, sr):
    key = field_key(SEED, role)
    g = np.fromfile(GOLDEN / f"jbl250_generate_{role}_{sr}.f32", dtype="<f4")
    t = np.fromfile(GOLDEN / f"jbl250_template_{role}_{sr}.f32", dtype="<f4")
    x, tm = jbl250.generate(key, role, sr), jbl250.template(key, role, sr)
    assert x.dtype == np.float32 and tm.dtype == np.float64
    assert x.size == t.size == round(0.25 * sr)
    assert np.max(np.abs(x - g)) <= 1e-6
    assert np.max(np.abs(tm - t)) <= 1e-6


@pytest.mark.parametrize("role,sr", CASES)
def test_live_fieldprobes(role, sr):
    """Same check against fieldprobes itself (read-only import); skipped where research/ or scipy is absent."""
    if not FIELDTEST.is_dir():
        pytest.skip("no research/ checkout")
    sys.path.insert(0, str(FIELDTEST))
    dwb, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # no writes under research/
    try:
        fp = pytest.importorskip("fieldprobes")
    finally:
        sys.path.remove(str(FIELDTEST))
        sys.dont_write_bytecode = dwb
    key = field_key(SEED, role)
    assert np.max(np.abs(jbl250.generate(key, role, sr) - fp.generate(SEED, "JBL250", role, sr))) <= 1e-6
    assert np.max(np.abs(jbl250.template(key, role, sr) - fp.template(SEED, "JBL250", role, sr))) <= 1e-6
    y, info = jbl250.render(key, role, sr, 6.0)
    y2, info2 = fp.render(SEED, "JBL250", role, sr, 6.0)
    assert np.max(np.abs(y - y2)) <= 1e-6 and info == pytest.approx(info2)


@pytest.mark.parametrize("sr", [36000, 44100, 48000, 96000])
def test_sample_rates(sr):
    key = jbl250.bed_key("11" * 32, "A", 0)
    x, info = jbl250.render(key, "A", sr)
    t = jbl250.template(key, "A", sr)
    assert x.size == t.size == info["n"] == round(0.25 * sr) and info["sr"] == sr
    assert info["rms"] == pytest.approx(K.TARGET_RMS, rel=1e-3) and info["peak"] <= K.MAX_PEAK
    # bed lives in 2-18 kHz, the tune below 1800 Hz
    f = np.fft.rfftfreq(t.size, 1 / sr)
    e = np.abs(np.fft.rfft(t)) ** 2
    assert e[(f >= 2000) & (f <= 18000)].sum() / e.sum() > 0.99
    tune = x.astype(np.float64) - t
    et = np.abs(np.fft.rfft(tune)) ** 2
    assert et[f < 1800].sum() / et.sum() > 0.99


@pytest.mark.parametrize("sr", [35999, 96001, 8000])
def test_bad_sample_rate(sr):
    with pytest.raises(ValueError):
        jbl250.generate(jbl250.bed_key("11" * 32, "A", 0), "A", sr)


def test_peak_limit():
    y, info = jbl250.render(jbl250.bed_key("11" * 32, "B", 0), "B", 48000, gain_db=40)
    assert info["peak"] <= K.MAX_PEAK and info["gain_db_applied"] < 40


def test_bed_key_derivation():
    seed = "ab" * 32
    keys = {(r, k): jbl250.bed_key(seed, r, k) for r in "AB" for k in (0, 1)}
    assert len(set(keys.values())) == 4 and all(len(v) == 32 for v in keys.values())
    assert keys["A", 0] == hashlib.sha256(f"pop-v1|{seed}|JBL250|A|0|bed".encode()).digest()
    assert jbl250.bed_key(seed.upper(), "A", 0) == keys["A", 0]
    assert jbl250.bed_key("cd" * 32, "A", 0) != keys["A", 0]
    t0, t1 = (jbl250.template(keys["A", k], "A", 48000) for k in (0, 1))
    assert abs(np.dot(t0, t1)) / (np.linalg.norm(t0) * np.linalg.norm(t1)) < 0.05
    with pytest.raises(ValueError):
        jbl250.bed_key(seed, "A", 2)
    with pytest.raises(ValueError):
        jbl250.bed_key(seed, "C", 0)


@pytest.mark.parametrize("role,sr", CASES)
def test_tune_boost_fixed_bed(role, sr):
    key = jbl250.bed_key("11" * 32, role, 0)
    s, j, b = jbl250._parts(key, role, sr)
    bed, tune = s * b, s * j
    tm = jbl250.template(key, role, sr)
    assert np.array_equal(tm, bed)
    y0, i0 = jbl250.render(key, role, sr)
    assert np.array_equal(y0, jbl250.generate(key, role, sr)) and "tune_db_applied" not in i0
    for tdb in (0.0, 4.0, 8.0, 12.0, 30.0):
        y, info = jbl250.render(key, role, sr, tune_db=tdb)
        assert info["peak"] <= K.MAX_PEAK
        g = 1.0 if tdb == 0 else 10 ** (info["tune_db_applied"] / 20)
        assert g <= 10 ** (tdb / 20) + 1e-12
        # bed part identical: play minus the (known) tune part is the tune_db=0 bed, to float32 rounding
        assert np.max(np.abs(y.astype(np.float64) - g * tune - bed)) <= 1e-6
        assert np.array_equal(jbl250.template(key, role, sr), tm)
        if tdb:
            assert info["tune_db_max"] >= info["tune_db_applied"]
            if tdb < info["tune_db_max"]:
                assert info["tune_db_applied"] == pytest.approx(tdb)
            else:
                assert info["tune_db_applied"] < tdb and info["peak"] > 0.9 * K.MAX_PEAK   # limited, not clipped
    assert np.max(np.abs(y0 - jbl250.render(key, role, sr, tune_db=0)[0])) == 0


def test_tune_boost_code_templates_unchanged():
    from pop import popt2
    key = jbl250.bed_key("22" * 32, "A", 0)
    before = popt2.code_wire(key, "A", 48000)
    for tdb in (0.0, 4.0, 8.0):
        jbl250.render(key, "A", 48000, tune_db=tdb)
        assert popt2.code_wire(key, "A", 48000) == before


def test_max_safe_tune_db():
    for sr in (44100, 48000):
        m = jbl250.max_safe_tune_db(sr)
        assert set(m) == {"A", "B"} and all(v > 0 for v in m.values())
