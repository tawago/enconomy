"""Enrollment calibration: a per-device self_os offset (cal_us), circuit-agnostic.

The app runs its audio check CAL_N times (same self_os_delta math as a run), takes the median in µs and
rejects when max - min > CAL_SPREAD_MAX_US or the median is outside 0..CAL_MAX_US; a median in
[-CAL_NEG_CLAMP_US, 0) is clamped to 0. from_samples() is that rule; the app's Calibration.fromSamples
must agree (tests on both sides pin the same vectors).

The plaintext self check becomes |self_os_delta - cal_frames| <= SELF_OS_TOL_MS (verdict.self_os_ok), exact:
|delta * 1e6 - cal_us * sr| <= SELF_OS_TOL_MS * 1000 * sr.

Enroll: the calibration object rides in the enroll body with cal_sig_b64 = device-key signature (raw r||s)
over message(nonce, cal). Recalibrate: POST /v1/device/calibration, covered by the signed-request auth.
SBcred3 / circuit inputs are untouched; the device row keeps cal_us so a future credential can carry it.
"""
from __future__ import annotations

from pop import constants as K

ROUTE_MAX = 64


class CalError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.code, self.detail = "bad_calibration", detail


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def from_samples(samples_us: list[int]) -> int:
    """CAL_N offsets (µs) -> cal_us, or CalError."""
    if not isinstance(samples_us, list) or len(samples_us) != K.CAL_N or not all(_int(v) for v in samples_us):
        raise CalError(f"need {K.CAL_N} integer samples_us")
    s = sorted(samples_us)
    if s[-1] - s[0] > K.CAL_SPREAD_MAX_US:
        raise CalError(f"spread {s[-1] - s[0]} us > {K.CAL_SPREAD_MAX_US}")
    med = s[len(s) // 2]
    if med < -K.CAL_NEG_CLAMP_US or med > K.CAL_MAX_US:
        raise CalError(f"median {med} us outside -{K.CAL_NEG_CLAMP_US}..{K.CAL_MAX_US}")
    return max(0, med)


def parse(cal) -> dict:
    """Request object -> stored dict {cal_us, sample_rate, route, backend, samples_us?}. CalError on anything off."""
    if not isinstance(cal, dict):
        raise CalError("calibration must be an object")
    cal_us, sr = cal.get("cal_us"), cal.get("sample_rate")
    if not _int(cal_us) or not 0 <= cal_us <= K.CAL_MAX_US:
        raise CalError(f"cal_us must be 0..{K.CAL_MAX_US}")
    if not _int(sr) or not K.SR_MIN <= sr <= K.SR_MAX:
        raise CalError(f"sample_rate must be {K.SR_MIN}..{K.SR_MAX}")
    out = {"cal_us": cal_us, "sample_rate": sr}
    for f in ("route", "backend"):
        v = cal.get(f, "")
        if not isinstance(v, str) or len(v) > ROUTE_MAX or "\n" in v:
            raise CalError(f"{f} must be a string up to {ROUTE_MAX} chars, no newline")
        out[f] = v
    if cal.get("samples_us") is not None:
        if from_samples(cal["samples_us"]) != cal_us:
            raise CalError("cal_us is not the rule applied to samples_us")
        out["samples_us"] = list(cal["samples_us"])
    return out


def message(nonce_hex: str, cal: dict) -> bytes:
    """What cal_sig_b64 signs at enroll: pop-cal-v1, enroll nonce, cal_us, sample_rate, route, backend."""
    return "\n".join(["pop-cal-v1", nonce_hex.lower(), str(cal["cal_us"]), str(cal["sample_rate"]),
                      cal["route"], cal["backend"]]).encode()


def public(dev: dict | None) -> dict | None:
    """Calibration as the API shows it (enroll response, session view, result record)."""
    if not dev or dev.get("cal_us") is None:
        return None
    return {"cal_us": dev["cal_us"], "sample_rate": dev.get("cal_sample_rate"), "route": dev.get("cal_route"),
            "backend": dev.get("cal_backend"), "at": dev.get("cal_at")}


def columns(cal: dict | None, at: str | None) -> dict:
    """Parsed calibration -> device row columns (all None when absent)."""
    if cal is None:
        return {"cal_us": None, "cal_sample_rate": None, "cal_route": None, "cal_backend": None, "cal_at": None,
                "cal_samples": None}
    return {"cal_us": cal["cal_us"], "cal_sample_rate": cal["sample_rate"], "cal_route": cal["route"],
            "cal_backend": cal["backend"], "cal_at": at,
            "cal_samples": ",".join(map(str, cal["samples_us"])) if cal.get("samples_us") else None}
