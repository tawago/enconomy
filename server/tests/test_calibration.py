"""Enrollment calibration (pop/calibration.py): the median rule, enroll + recalibrate over HTTP, the calibrated
self check in the verdict (unit and full v2 flow), and cal_us in the view and result record."""
import base64

import pytest

from pop import calibration as CAL
from pop import constants as K
from pop.crypto import sign_raw
from pop.verdict import self_os_ok, verify_record
from tests.phones import Phone, make_chain
from tests.sim import Knobs
from tests.test_flow_v2 import world  # noqa: F401  (fixture)

# Same vectors as the app's CalibrationTest (commonTest).
RULE = [
    ([20000, 20100, 19900, 20050, 19950], 20000),
    ([-400, -500, -600, -450, -550], 0),           # median -500 clamps to 0
    ([-2000, -1900, -2100, -1950, -2050], 0),      # median exactly -2 ms: clamp
    ([50000, 49900, 50100, 49950, 50050], 50000),  # median exactly 50 ms: ok
]


@pytest.mark.parametrize("samples,want", RULE)
def test_rule(samples, want):
    assert CAL.from_samples(samples) == want


@pytest.mark.parametrize("samples,why", [
    ([0, 0, 0, 0, 1001], "spread"),
    ([-2100, -2050, -2001, -2200, -2150], "median"),
    ([50001, 50001, 50001, 50001, 50001], "median"),
    ([1, 2, 3, 4], "5 integer"),
    ([1, 2, 3, 4, 5.0], "5 integer"),
])
def test_rule_rejects(samples, why):
    with pytest.raises(CAL.CalError, match=why):
        CAL.from_samples(samples)


def test_self_os_ok_calibrated():
    sr = 48000
    assert self_os_ok(2400, sr) and not self_os_ok(2401, sr)            # uncalibrated: the old |d| <= 50 ms
    cal = 30000                                                          # 30 ms = 1440 frames at 48 kHz
    assert self_os_ok(1440 + 2400, sr, cal) and not self_os_ok(1440 + 2401, sr, cal)
    assert self_os_ok(1440 - 2400, sr, cal) and not self_os_ok(1440 - 2401, sr, cal)
    # non-integer cal_frames at 44.1 kHz: exact |d*1e6 - cal*sr| <= 50e3*sr
    assert self_os_ok(1323 + 2205, 44100, 30000) and not self_os_ok(1323 + 2206, 44100, 30000)


def _cal(cal_us=12000, **kw):
    return {"cal_us": cal_us, "sample_rate": 48000, "route": "speaker", "backend": "aaudio", **kw}


def _enroll(client, p: Phone, cal: dict | None, sig: bytes | None = None, attested=True):
    n = client.get("/v1/enroll/nonce").json()["nonce"]
    body = p.enroll_body(n, make_chain(p.sk.public_key(), bytes.fromhex(n)) if attested else None)
    if cal is not None:
        c = CAL.parse(cal)
        body["calibration"] = cal
        body["cal_sig_b64"] = base64.b64encode(sig if sig is not None else sign_raw(p.sk, CAL.message(n, c))).decode()
    return client.post("/v1/enroll", json=body)


def test_enroll_with_calibration(client, clock):
    p = Phone(client, clock)
    r = _enroll(client, p, _cal(samples_us=[12000, 11900, 12100, 12050, 11950]))
    assert r.status_code == 200, r.text
    c = r.json()["calibration"]
    assert c["cal_us"] == 12000 and c["sample_rate"] == 48000 and c["route"] == "speaker" and c["backend"] == "aaudio"
    d = client.app.state.store.get_device(p.device_id)
    assert d["cal_us"] == 12000 and d["cal_samples"] == "12000,11900,12100,12050,11950"
    assert d["cred"] is None  # SBcred3 untouched: no holder_commit, no credential


def test_enroll_without_calibration(client, clock):
    p = Phone(client, clock)
    r = _enroll(client, p, None)
    assert r.status_code == 200 and r.json()["calibration"] is None


@pytest.mark.parametrize("cal,sig,err", [
    (_cal(50001), None, "cal_us"),
    (_cal(-1), None, "cal_us"),
    (_cal(sample_rate=8000), None, "sample_rate"),
    (_cal(samples_us=[0, 0, 0, 0, 1001], cal_us=0), None, "spread"),
    (_cal(samples_us=[1, 1, 1, 1, 1], cal_us=5), None, "rule"),
    (_cal(), b"\x00" * 64, "signature"),
])
def test_enroll_bad_calibration(client, clock, cal, sig, err):
    p = Phone(client, clock)
    n = client.get("/v1/enroll/nonce").json()["nonce"]
    body = p.enroll_body(n, make_chain(p.sk.public_key(), bytes.fromhex(n)))
    body["calibration"] = cal
    try:
        msg = CAL.message(n, CAL.parse(cal))
    except CAL.CalError:
        msg = b"x"
    body["cal_sig_b64"] = base64.b64encode(sig if sig is not None else sign_raw(p.sk, msg)).decode()
    r = client.post("/v1/enroll", json=body)
    assert r.status_code == 400 and r.json()["error"] == "bad_calibration" and err in r.json()["detail"], r.text
    assert client.app.state.store.get_device(p.device_id) is None


def test_cal_sig_bound_to_nonce(client, clock):
    p = Phone(client, clock)
    other = client.get("/v1/enroll/nonce").json()["nonce"]
    r = _enroll(client, p, _cal(), sig=sign_raw(p.sk, CAL.message(other, CAL.parse(_cal()))))
    assert r.status_code == 400 and r.json()["error"] == "bad_calibration"


def test_recalibrate(client, clock):
    p = Phone(client, clock)
    assert _enroll(client, p, _cal(12000)).status_code == 200
    r = p.post("/v1/device/calibration", {"calibration": _cal(30000, backend="opensl")})
    assert r.status_code == 200, r.text
    assert r.json()["calibration"]["cal_us"] == 30000 and r.json()["calibration"]["backend"] == "opensl"
    assert client.app.state.store.get_device(p.device_id)["cal_us"] == 30000
    bad = p.post("/v1/device/calibration", {"calibration": _cal(60000)})
    assert bad.status_code == 400 and bad.json()["error"] == "bad_calibration"
    assert client.app.state.store.get_device(p.device_id)["cal_us"] == 30000
    # unsigned: rejected by auth
    assert client.post("/v1/device/calibration", json={"calibration": _cal()}).status_code == 401


def _calibrate(w, role, cal_us):
    p = w.a if role == "A" else w.b
    r = p.post("/v1/device/calibration", {"calibration": {**_cal(cal_us), "sample_rate": p.k.sr}})
    assert r.status_code == 200, r.text


def test_flow_calibrated_self_check(world):  # noqa: F811
    """v2: a phone whose OS timestamps sit 80 ms off, calibrated at 40 ms, folds cal into p_self and signs the
    40 ms residual (1920 frames); the server checks it as is (|40| <= 50), cal is not subtracted again."""
    w = world(30, ka=Knobs(self_os_delta_override=1920), real_root=False)   # 80 - 40 ms at 48 kHz
    _calibrate(w, "A", 40000)
    w.run_attempt(0)
    v = w.view()
    assert v["state"] == "done", v
    rec = w.result().json()
    assert rec["verdict"] == "NEAR" and rec["devices"]["A"]["cal_us"] == 40000 and rec["devices"]["B"]["cal_us"] == 0
    assert verify_record(rec)["verdict"] == "NEAR"
    assert w.view(w.a)["self"]["cal_us"] == 40000 and w.view(w.b)["partner"]["cal_us"] == 40000
    # v2: the signed residual carries the calibration; the record's cal_us does not change the offline check
    rec["devices"]["A"]["cal_us"] = 0
    assert verify_record(rec)["verdict"] == "NEAR"


def test_flow_uncalibrated_same_offset_retries(world):  # noqa: F811
    w = world(30, ka=Knobs(self_os_delta_override=3840), real_root=False)
    w.run_attempt(0)
    v = w.view()
    assert v["attempt"] == 1 and v["last_failure"]["reason"] == "self_timestamp_mismatch"


def test_flow_calibration_not_subtracted_twice(world):  # noqa: F811
    """v2: a calibrated phone (cal 40 ms) that signs an uncalibrated 80 ms offset fails: the server no longer
    subtracts cal from a v2 self_os_delta."""
    w = world(30, ka=Knobs(self_os_delta_override=3840), real_root=False)
    _calibrate(w, "A", 40000)
    w.run_attempt(0)
    v = w.view()
    assert v["attempt"] == 1 and v["last_failure"]["reason"] == "self_timestamp_mismatch"


def test_self_os_ok_v1_keeps_cal():
    from pop.verdict import self_os_ok   # v1 rule: |sod - cal| <= tol
    assert self_os_ok(3840, 48000, 40000) and not self_os_ok(3840, 48000, 0)


def test_config_exports_cal_constants(client):
    c = client.get("/v1/config").json()
    assert {k: c[k] for k in ("cal_n", "cal_spread_max_us", "cal_max_us", "cal_neg_clamp_us", "self_os_tol_ms")} == {
        "cal_n": K.CAL_N, "cal_spread_max_us": 1000, "cal_max_us": 50000, "cal_neg_clamp_us": 2000, "self_os_tol_ms": 50}


def test_message_layout_matches_app():
    """Pinned in the app's CalibrationTest.signedMessageLayout."""
    c = CAL.parse({"cal_us": 12000, "sample_rate": 48000, "route": "speaker", "backend": "aaudio/unprocessed"})
    assert CAL.message("ABCD", c) == b"pop-cal-v1\nabcd\n12000\n48000\nspeaker\naaudio/unprocessed"
