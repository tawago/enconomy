import hashlib

import numpy as np
import pytest

from pop import constants as K
from pop import dsp_ref as D
from pop.verdict import decide, flight_cm, self_os_ok


def halves(d_cm, sr_a, sr_b, gap_s=0.95, lat_a=0.012, lat_b=0.031):
    """A: t_BA - t_AA ; B: t_BB - t_AB, each on its own clock and sample rate."""
    tof = d_cm / K.SPEED_OF_SOUND_CM_S
    on_a, on_b = lat_a, gap_s + lat_b
    return round((on_b + tof - on_a) * sr_a), round((on_b - (on_a + tof)) * sr_b)


@pytest.mark.parametrize("sr_a,sr_b", [(48000, 48000), (48000, 44100), (44100, 48000), (96000, 36000)])
@pytest.mark.parametrize("d", [0, 30, 59, 100, 200])
def test_flight_mixed_rates(d, sr_a, sr_b):
    ha, hb = halves(d, sr_a, sr_b)
    assert flight_cm(ha, sr_a, hb, sr_b) == pytest.approx(d, abs=0.6)


def test_swap_flips_sign():
    ha, hb = halves(100, 48000, 48000)
    assert flight_cm(ha, 48000, hb, 48000) == pytest.approx(100, abs=0.5)
    assert flight_cm(hb, 48000, ha, 48000) == pytest.approx(-100, abs=0.5)   # why the pair checks exist


@pytest.mark.parametrize("f,out", [(-25, (None, "impossible_flight")), (-20, (None, "impossible_flight")),
                                   (-19.9, ("NEAR", None)), (0, ("NEAR", None)), (59.99, ("NEAR", None)),
                                   (60, ("NOT_NEAR", "too_far")), (250, ("NOT_NEAR", "too_far"))])
def test_decide(f, out):
    assert decide(f) == out


def test_self_os_tol():
    assert self_os_ok(2400, 48000) and self_os_ok(-2400, 48000) and not self_os_ok(2401, 48000)


def test_null_codes_pinned():
    x = D.null_template("00" * 16, "A", 0, 0, 48000)
    assert x.size == 12000
    lit = [-2.171744575836746e-08, 5.97041846600107e-07, 1.8355747627008143e-06, -1.903719598807515e-06,
           -5.523028857828255e-06, -1.7134374804790278e-05, -1.340421762003768e-05, 1.0695781803152786e-05]
    assert np.allclose(x[:8], lit, rtol=1e-9, atol=0)
    assert hashlib.sha256("".join("%.12e" % v for v in x).encode()).hexdigest() == \
        "50e441675a89a670bb18d9a2dca94fce8289d40cb51dec8eddb134073bece71b"
    assert not np.array_equal(x, D.null_template("00" * 16, "A", 1, 0, 48000))
    assert not np.array_equal(x, D.null_template("00" * 16, "B", 0, 0, 48000))


def test_gumbel_matches_scipy():
    stats = pytest.importorskip("scipy.stats")
    rng = np.random.default_rng(3)
    p = K.NULL_P / K.NULL_P_SAFETY
    for _ in range(10):
        s = stats.gumbel_r.rvs(loc=0.06, scale=0.004, size=64, random_state=rng)
        want = stats.gumbel_r.isf(p, *stats.gumbel_r.fit(s))
        assert D.gumbel_isf(s, p) == pytest.approx(want, rel=0.01)


def test_flat_runs():
    rng = np.random.default_rng(0)
    x = rng.integers(-3000, 3000, 48000).astype(np.int16)
    assert D.flat_runs(x, 48000) == []
    x[10000:10960] = 0          # 20 ms block
    runs = D.flat_runs(x, 48000)
    assert len(runs) == 1 and runs[0][0] == 10000 and runs[0][1] in (10959, 10960)
    x[20000:20300] = 5          # 6 ms: below the 8 ms minimum
    assert len(D.flat_runs(x, 48000)) == 1
    assert D.glitch(runs, 10900, 11000) and not D.glitch(runs, 11000, 12000)
