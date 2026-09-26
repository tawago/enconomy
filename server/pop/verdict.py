"""Transcript checks, combination, flight and verdict (contract §7, §8). Pure; no session state.

check_transcript()  one signed transcript against what the server knows about its sender.
combine()           both halves of one attempt -> flight_cm, verdict, reason.
verify_record()     re-run every check offline from a §8.4 result record (what ZK/onchain gets).

  flight_cm = c/2 * (half_A/sr_A - half_B/sr_B)       exact (Fraction) for the decision, rounded for display
  NEAR iff IMPOSSIBLE_CM < flight < NEAR_CM;  flight <= IMPOSSIBLE_CM -> impossible_flight (retry);
  flight >= NEAR_CM -> NOT_NEAR too_far (never retried).
  Exact ties decide like the oa2t_pair circuit: c*N <= -40*S impossible, c*N >= 120*S too far
  (N = hA*srB - hB*srA, S = srA*srB).

POPT v2 (docs/pop-transcript-v2.md): same verdict math. check_transcript also pins the version the phone armed
with, rec_root against the POPC v2 commit, delta = DELTA_MS*sr//1000 and code_commit against the codes the
server sent. SELF_OS_TOL_MS applies to both versions.

Swapping the two halves flips the sign (100 cm -> -100 cm), so the pair checks pin role, nonce,
attempt and the key pair on both sides; a swapped pair is transcript_mismatch, not a flight.
Exactly -20 cm counts as impossible (the contract's check says >= -20 passes but its verdict
needs > -20; the stricter side wins).
"""
from __future__ import annotations

import hashlib
import hmac
from fractions import Fraction

from pop import constants as K
from pop.codec import REC_KEY, b64d, decode_commit, decode_transcript, version_of
from pop.popt2 import delta as popt2_delta
from pop.crypto import verify_raw

# measurement failures: retried at attempt 0, final at the last attempt
RETRY_REASONS = {"capture_failed", "glitch", "self_not_heard", "self_timestamp_mismatch", "partner_not_heard",
                 "impossible_flight", "timeout"}
# a phone may report these at POST /fail; partner_mismatch is final (bad invite, not a measurement)
PHONE_REASONS = {"capture_failed", "glitch", "self_not_heard", "self_timestamp_mismatch", "partner_not_heard",
                 "partner_mismatch"}
FINAL_REASONS = {"too_far", "signature_invalid", "transcript_mismatch", "partner_mismatch", "aborted"}

USER_TEXT = {
    "too_far": "Too far apart. Hold the phones side by side.",
    "partner_not_heard": "Partner not heard. Check volume and try again.",
    "self_not_heard": "Your own sound was not heard. Check volume and mic.",
    "glitch": "Recording glitch, trying again.",
    "impossible_flight": "Measurement failed, trying again.",
    "self_timestamp_mismatch": "Audio timing off, trying again.",
    "capture_failed": "Audio capture failed, trying again.",
    "timeout": "Partner did not finish in time.",
    "signature_invalid": "Device signature invalid.",
    "transcript_mismatch": "Session data mismatch.",
    "partner_mismatch": "Invite does not match this partner.",
    "aborted": "Session aborted.",
}


class Reject(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


def self_os_ok(delta_frames: int, sr: int) -> bool:
    """|self_os_delta| <= SELF_OS_TOL_MS at sr, exact integers."""
    return abs(int(delta_frames)) * 1000 <= K.SELF_OS_TOL_MS * int(sr)


def flight_exact(half_a: int, sr_a: int, half_b: int, sr_b: int) -> Fraction:
    return Fraction(K.SPEED_OF_SOUND_CM_S, 2) * (Fraction(int(half_a), int(sr_a)) - Fraction(int(half_b), int(sr_b)))


def flight_cm(half_a: int, sr_a: int, half_b: int, sr_b: int) -> float:
    return float(flight_exact(half_a, sr_a, half_b, sr_b))


def decide(flight) -> tuple[str | None, str | None]:
    """(verdict, reason). verdict None = measurement failure, retry per §8.2.
    Pass flight_exact() (Fraction) for circuit-exact ties; a float is compared as given."""
    if flight <= K.IMPOSSIBLE_CM:
        return None, "impossible_flight"
    if flight >= K.NEAR_CM:
        return "NOT_NEAR", "too_far"
    return "NEAR", None


def check_commit(commit_raw: bytes, sig: bytes, *, role: str, pk: bytes, nonce: bytes, attempt: int) -> dict:
    try:
        c = decode_commit(commit_raw)
    except ValueError as e:
        raise Reject("transcript_mismatch", f"commit: {e}") from None
    if not verify_raw(pk, commit_raw, sig):
        raise Reject("signature_invalid", "commit")
    if c["role"] != role or c["attempt"] != attempt or not hmac.compare_digest(c["nonce"], nonce):
        raise Reject("transcript_mismatch", "commit role/attempt/nonce")
    return c


def check_transcript(raw: bytes, sig: bytes, *, role: str, pk_self: bytes, pk_partner: bytes, nonce: bytes,
                     attempt: int, commit_sha256: bytes | None, rec: bytes | None,
                     sample_rate: int | None = None, version: int = 1, code_commit: bytes | None = None) -> dict:
    """One transcript vs its sender (enrolled key pk_self, session role). Raises Reject; returns decoded.

    Order: layout, signature, version, pk_self, role, nonce/attempt, pk_partner, sample_rate, commitment
    (commit_hash, rec), then v2 only: delta, code_commit (skipped when code_commit is None, e.g. offline).
    rec = the committed rec_sha256 (v1) / rec_root (v2). self_os_delta is NOT checked here (a measurement
    failure, not a broken client; see combine()).
    """
    try:
        t = decode_transcript(raw)
    except ValueError as e:
        raise Reject("transcript_mismatch", str(e)) from None
    if not verify_raw(pk_self, raw, sig):
        raise Reject("signature_invalid", "transcript signature")
    if version_of(t) != version:
        raise Reject("transcript_mismatch", f"POPT version {version_of(t)} != armed {version}")
    if t["pk_self"] != pk_self:
        raise Reject("signature_invalid", "pk_self is not the sender's enrolled key")
    if t["role"] != role:
        raise Reject("transcript_mismatch", f"role {t['role']} from the {role} device")
    if t["nonce"] != nonce:
        raise Reject("transcript_mismatch", "session_nonce")
    if t["attempt"] != attempt:
        raise Reject("transcript_mismatch", f"attempt {t['attempt']} != {attempt}")
    if t["pk_partner"] != pk_partner:
        raise Reject("transcript_mismatch", "pk_partner is not the session partner")
    if sample_rate is not None and t["sample_rate"] != sample_rate:
        raise Reject("transcript_mismatch", f"sample_rate {t['sample_rate']} != armed {sample_rate}")
    if not K.SR_MIN <= t["sample_rate"] <= K.SR_MAX:
        raise Reject("transcript_mismatch", "sample_rate out of range")
    if commit_sha256 is None or t["commit_hash"] != commit_sha256:
        raise Reject("transcript_mismatch", "commit_hash does not match the stored commit")
    key = REC_KEY[version]
    if rec is None or t[key] != rec:
        raise Reject("transcript_mismatch", f"{key} does not match the commit")
    if version == 2:
        if t["delta"] != popt2_delta(t["sample_rate"]):
            raise Reject("transcript_mismatch", f"delta {t['delta']} != {popt2_delta(t['sample_rate'])}")
        if code_commit is not None and not hmac.compare_digest(t["code_commit"], code_commit):
            raise Reject("transcript_mismatch", "code_commit is not the codes the server sent")
    return t


def combine(ta: dict, tb: dict) -> dict:
    """Both decoded, individually checked transcripts of one attempt -> {flight_cm, verdict, reason}.

    Pair checks repeat what check_transcript pinned per side, so this is safe on its own too.
    """
    if ta["role"] != "A" or tb["role"] != "B":
        raise Reject("transcript_mismatch", "need one A and one B")
    if ta["nonce"] != tb["nonce"] or ta["attempt"] != tb["attempt"]:
        raise Reject("transcript_mismatch", "nonce/attempt differ")
    if ta["pk_partner"] != tb["pk_self"] or tb["pk_partner"] != ta["pk_self"] or ta["pk_self"] == tb["pk_self"]:
        raise Reject("transcript_mismatch", "key pair differs")
    for t in (ta, tb):
        if not self_os_ok(t["self_os_delta"], t["sample_rate"]):
            return {"flight_cm": None, "verdict": None, "reason": "self_timestamp_mismatch", "by": t["role"]}
    f = flight_exact(ta["half"], ta["sample_rate"], tb["half"], tb["sample_rate"])
    v, why = decide(f)
    return {"flight_cm": round(float(f), 2), "verdict": v, "reason": why, "by": None}


def verify_record(rec: dict) -> dict:
    """Offline re-check of a §8.4 record: signatures by the listed pubkeys, commits, pair checks, flight.

    Returns combine()'s dict; raises Reject. Only meaningful for records that carry both transcripts.
    v2: the version comes from the commit; code_commit can't be re-derived offline (no seed), so it isn't checked.
    """
    nonce = bytes.fromhex(rec["session_nonce"])
    pk = {r: bytes.fromhex(rec["devices"][r]["pubkey"]) for r in ("A", "B")}
    got = {}
    for r, other in (("A", "B"), ("B", "A")):
        tr, cm = rec["transcripts"].get(r), (rec.get("commits") or {}).get(r)
        if not tr or not cm:
            raise Reject("transcript_mismatch", f"record has no {r} transcript/commit")
        craw = b64d(cm["commit_b64"])
        c = check_commit(craw, b64d(cm["sig_b64"]), role=r, pk=pk[r], nonce=nonce, attempt=rec["attempt"])
        ver = version_of(c)
        got[r] = check_transcript(b64d(tr["transcript_b64"]), b64d(tr["sig_b64"]), role=r, pk_self=pk[r],
                                  pk_partner=pk[other], nonce=nonce, attempt=rec["attempt"],
                                  commit_sha256=hashlib.sha256(craw).digest(), rec=c[REC_KEY[ver]], version=ver)
    return combine(got["A"], got["B"])
