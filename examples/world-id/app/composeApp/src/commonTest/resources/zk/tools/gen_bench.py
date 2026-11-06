"""Writes the prover bench fixtures (commonMain/composeResources/files/zk/bench_<name>.json) from the spike.

Run: $PY gen_bench.py   ($PY = research/proximity-echo/.venv/bin/python3). Reads research/ only.
Needs the spike's optionA-v2/build/popt2 captures and optionA-v2/inputs (both gitignored there).

One fixture = everything a phone holds after a POPT v2 run: signed transcript + sig, the int16 capture,
own/partner int8 codes, SBcred3 + issuer sig, issuer pub, validAt, salt. The app builds the witness from
it exactly as after a real run (WitnessInput). `expect` holds sha256 of each witness field as compact JSON
(prep_popt2.py output), the public vector digest and halfCommit, so tests and the bench can check parity.
"""
import base64
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True  # nothing lands in research/
HERE = Path(__file__).resolve().parent
SRC = HERE.parents[3]
OUT = SRC / "commonMain/composeResources/files/zk"
REPO = HERE.parents[6]
ZK = REPO / "research/sound-bound/spikes/zk"
OA2 = ZK / "optionA-v2"
sys.path.insert(0, str(OA2))
sys.path.insert(0, str(OA2 / "poseidon7"))
import oa_rate as R  # noqa: E402

VALID_AT = 1790000000
CASES = [("180ca04b", "48k", "A"), ("180ca04b", "mix", "B")]


def c(v):
    return json.dumps(v, separators=(",", ":"))


def i8(v):
    return base64.b64encode(np.asarray(v, dtype=np.int8).tobytes()).decode()


def raw_rs(r_hex, s_hex):
    return base64.b64encode(bytes.fromhex(r_hex.rjust(64, "0")) + bytes.fromhex(s_hex.rjust(64, "0"))).decode()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for s8, mode, role in CASES:
        name = f"{s8}_{mode}_{role}"
        fx = json.loads((ZK / "fixtures/popt_v2" / f"{s8}_{mode}.json").read_text())
        r = fx["roles"][role]
        sr = int(r["sample_rate"])
        other = "B" if role == "A" else "A"
        tI, tQ = R.templates(fx["seed_hex"], role, sr)
        pI, pQ = R.templates(fx["seed_hex"], other, sr)
        assert R.code_commit(tI, tQ, pI, pQ).hex() == r["code_commit"]
        x = np.load(ZK / r["capture_npy"]).astype("<i2")
        inp = json.loads((OA2 / "inputs" / f"popt2_{s8}_{mode}_{role}.input.json").read_text())
        pub = json.loads((OA2 / "inputs" / f"popt2_{s8}_{mode}_{role}.public.json").read_text())["public"]
        iss = fx["issuer"]
        out = {
            "name": name, "circuit": f"oa2t_s{sr // 1000}", "sample_rate": sr, "role": role,
            "transcript_b64": r["transcript_b64"], "sig_b64": r["sig_b64"],
            "capture_b64": base64.b64encode(x.tobytes()).decode(),
            "own_cI_b64": i8(tI), "own_cQ_b64": i8(tQ), "partner_cI_b64": i8(pI), "partner_cQ_b64": i8(pQ),
            "cred_b64": base64.b64encode(bytes.fromhex(r["cred_hex"])).decode(),
            "cred_sig_b64": raw_rs(r["cred_sig_r_hex"], r["cred_sig_s_hex"]),
            "issuer_pub": "04" + iss["pub_x"].rjust(64, "0") + iss["pub_y"].rjust(64, "0"),
            "valid_at": VALID_AT,
            "salt_hex": r["salt_dev"][2:].rjust(62, "0"),
            "expect": {
                "half_commit": pub[0],
                "public_sha256": hashlib.sha256(c(pub).encode()).hexdigest(),
                "n_public": len(pub),
                "input_sha256": {k: hashlib.sha256(c(v).encode()).hexdigest() for k, v in sorted(inp.items())},
            },
        }
        (OUT / f"bench_{name}.json").write_text(json.dumps(out, indent=1) + "\n")
        print(name, sr, len(pub), "fields", len(inp))


if __name__ == "__main__":
    main()
