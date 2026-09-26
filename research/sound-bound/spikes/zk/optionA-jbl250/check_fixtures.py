"""Twin halves vs the signed fixture halves (../fixtures/*.json): same verdict? within 1 sample?"""
import json
from pathlib import Path
rows = {json.loads(l)["session"]: json.loads(l) for l in open(Path(__file__).parent / "build/twin_all.jsonl")
        if "flight_twin" in json.loads(l)}
ok = 0
for f in sorted((Path(__file__).parent.parent / "fixtures").glob("*.json")):
    fx = json.loads(f.read_text())
    s = fx["session_id"][:8]
    t = rows[s]
    hA, hB = fx["roles"]["A"]["half_samples"], fx["roles"]["B"]["half_samples"]
    v = "NEAR" if -20 < t["flight_twin"] < 60 else "NOT_NEAR"
    good = abs(t["halfA"] - hA) <= 1 and abs(t["halfB"] - hB) <= 1 and v == fx["verdict"]
    ok += good
    print(f"{s} label {fx['label_cm']:5.0f}  halfA {hA} twin {t['halfA']} ({t['halfA']-hA:+d})  "
          f"halfB {hB} twin {t['halfB']} ({t['halfB']-hB:+d})  flight {fx['flight_cm']:6.1f} twin {t['flight_twin']:6.1f}  "
          f"{fx['verdict']:8s} twin {v:8s} {'ok' if good else 'MISMATCH'}")
print(f"{ok}/{len(rows)} fixtures: halves within 1 sample and same verdict")
