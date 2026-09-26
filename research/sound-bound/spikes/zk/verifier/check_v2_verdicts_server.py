"""POPT v2 fixtures: server/pop/verdict decide(flight_cm(...)) and self_os_ok on each fixture's signed halves / rates
equals the fixture's expected verdict (the plaintext path, which the v2 codec would feed unchanged).
  server/.venv/bin/python research/sound-bound/spikes/zk/verifier/check_v2_verdicts_server.py"""
import base64, glob, json, sys
from pathlib import Path
ZK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ZK.parents[3] / "server")); sys.path.insert(0, str(ZK / "enclave"))
from pop.verdict import decide, flight_cm, self_os_ok  # noqa: E402
import popt  # noqa: E402
ok = True
for f in sorted(glob.glob(str(ZK / "fixtures/popt_v2/*.json"))):
    fx = json.load(open(f))
    t = {r: popt.decode(base64.b64decode(fx["roles"][r]["transcript_b64"])) for r in "AB"}
    if not all(self_os_ok(t[r]["self_os_delta"], t[r]["sample_rate"]) for r in "AB"):
        got = (None, "self_timestamp_mismatch")
    else:
        got = decide(flight_cm(t["A"]["half"], t["A"]["sample_rate"], t["B"]["half"], t["B"]["sample_rate"]))
    want = (fx["expect"]["verdict"], fx["expect"]["reason"])
    ok &= got == want
    print(f"{'PASS' if got == want else 'FAIL'} {fx['name']:22} server={got} expect={want}")
sys.exit(0 if ok else 1)
