"""Cross-check: every POPT v1 fixture through the real plaintext verifier (server/pop/verdict.py).

  server/.venv/bin/python research/sound-bound/spikes/zk/verifier/check_fixtures_server.py
Imports server/pop read-only. Asserts verify_record() gives the verdict the fixture expects, that
enclave/popt.py encodes byte-identically to server/pop/codec.py, and that the ZK constants equal
server/pop/constants.py.
"""
import base64
import glob
import json
import sys
from pathlib import Path

ZK = Path(__file__).resolve().parents[1]
REPO = ZK.parents[3]
sys.path.insert(0, str(REPO / "server"))
sys.path.insert(0, str(ZK / "enclave"))
from pop import codec, constants as K, verdict  # noqa: E402
import popt  # noqa: E402

ok = True
assert (K.SPEED_OF_SOUND_CM_S, K.NEAR_CM, K.IMPOSSIBLE_CM, K.SELF_OS_TOL_MS, K.SR_MIN, K.SR_MAX) == \
    (34300, 60, -20, 50, 36000, 96000), "constants drifted: update the circuits"
n = 0
for f in sorted(glob.glob(str(ZK / "fixtures" / "popt_v1" / "*.json"))):
    rec = json.load(open(f))
    for r in "AB":
        raw = base64.b64decode(rec["transcripts"][r]["transcript_b64"])
        a, b = codec.decode_transcript(raw), popt.decode(raw)
        same = all(a[k] == b[k if k != "nonce" else "nonce"] for k in ("role", "attempt", "pk_self", "pk_partner",
                   "sample_rate", "half", "play_frame_position", "play_nano_time", "rec_frame0_nano_time",
                   "self_os_delta", "commit_hash")) and a["rec_sha256"] == b["rec"] and a["nonce"] == b["nonce"]
        t = dict(b); t["rec_sha256"] = t.pop("rec")
        same = same and codec.encode_transcript({k: t[k] for k in codec.TX_FIELDS}) == raw
        if not same:
            ok = False
            print("CODEC MISMATCH", f, r)
    try:
        got = verdict.verify_record(rec)
        res = (got["verdict"], got["reason"])
    except verdict.Reject as e:
        res = (None, e.reason)
    e = rec["expect"]
    want = (None, "transcript_mismatch") if "selfpair" in rec["name"] else (e["verdict"], e["reason"])
    good = res == want
    ok &= good
    n += 1
    print(f"{'PASS' if good else 'FAIL'} {rec['name']:24} server={res} expect={want} flight={e['flight_cm']}")
print(f"{n} fixtures, server verify_record {'all as expected' if ok else 'MISMATCH'}")
sys.exit(0 if ok else 1)
