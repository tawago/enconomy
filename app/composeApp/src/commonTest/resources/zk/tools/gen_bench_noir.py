"""Prover bench fixtures for the Noir circuit (commonMain/composeResources/files/zk/bench_180ca04b_48k_{A,B}.json).

Run: uv run --with numpy python3 gen_bench_noir.py
Reads the spike (research/sound-bound/spikes/zk, main checkout: captures + inputs are gitignored) for the capture
and templates, and the ZK team's optA-noir outputs (~/.enconomy/zk/optA/noir: prep_*.json = the transcript
re-signed with the Poseidon2 rec_root + code_commit, Prover_{A,B}.toml) and ~/.enconomy/zk/pinned/{A,B}/public_inputs.
`expect.input_sha256` = sha256 of each Prover.toml value as compact JSON (what WitnessInput must produce).
"""
import base64
import hashlib
import json
import os
import sys
import tomllib
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OUT = HERE.parents[3] / "commonMain/composeResources/files/zk"
ZK = Path(os.environ.get("POP_SPIKE_ZK", str(Path.home() / "dev/enconomy/research/sound-bound/spikes/zk")))
OA2 = ZK / "optionA-v2"
sys.path.insert(0, str(OA2))
sys.path.insert(0, str(OA2 / "poseidon7"))
import oa_rate as R  # noqa: E402

NOIR = Path.home() / ".enconomy/zk/optA/noir"
PIN = Path.home() / ".enconomy/zk/pinned"
VALID_AT = 1790000000


def c(v):
    return json.dumps(v, separators=(",", ":"))


def i8(v):
    return base64.b64encode(np.asarray(v, dtype=np.int8).tobytes()).decode()


def main():
    fx = json.loads((ZK / "fixtures/popt_v2/180ca04b_48k.json").read_text())
    for role in "AB":
        name = f"180ca04b_48k_{role}"
        r = fx["roles"][role]
        sr = int(r["sample_rate"])
        other = "B" if role == "A" else "A"
        tI, tQ = R.templates(fx["seed_hex"], role, sr)
        pI, pQ = R.templates(fx["seed_hex"], other, sr)
        npy = ZK / r["capture_npy"]
        if npy.exists():
            x = np.load(npy).astype("<i2")
        else:  # regenerate from the field WAV like gen_inputs.py
            sys.path.insert(0, str(ZK / "enclave"))
            import emulate as em
            x = np.asarray(em.capture(em.session_dir(fx["field_session_id"][:8]), role, sr)[0]).astype("<i2")
        assert len(x) == int(r["capture_frames"]), len(x)
        prep = json.loads((NOIR / f"prep_180ca04b_48k_{role}.json").read_text())
        toml = tomllib.loads((NOIR / "phone" / f"Prover_{role}.toml").read_text())
        pub = (PIN / role / "public_inputs").read_bytes()
        assert len(pub) == 384
        iss = fx["issuer"]
        out = {
            "name": name, "circuit": "oaN_s48", "sample_rate": sr, "role": role,
            "transcript_b64": base64.b64encode(bytes.fromhex(prep["transcript_onchain"])).decode(),
            # the Prover.toml signature (ECDSA is randomized; prep_*.json may hold another valid one)
            "sig_b64": base64.b64encode(bytes(toml["sig"])).decode(),
            "capture_b64": base64.b64encode(x.tobytes()).decode(),
            "own_cI_b64": i8(tI), "own_cQ_b64": i8(tQ), "partner_cI_b64": i8(pI), "partner_cQ_b64": i8(pQ),
            "cred_b64": base64.b64encode(bytes.fromhex(r["cred_hex"])).decode(),
            "cred_sig_b64": base64.b64encode(bytes.fromhex(r["cred_sig_r_hex"].rjust(64, "0") + r["cred_sig_s_hex"].rjust(64, "0"))).decode(),
            "issuer_pub": "04" + iss["pub_x"].rjust(64, "0") + iss["pub_y"].rjust(64, "0"),
            "valid_at": VALID_AT,
            "salt_hex": r["salt_dev"][2:].rjust(62, "0"),
            "expect": {
                "half_commit": str(int.from_bytes(pub[352:384], "big")),
                "public_inputs_hex": pub.hex(),
                "input_sha256": {k: hashlib.sha256(c(v).encode()).hexdigest() for k, v in sorted(toml.items())},
            },
        }
        (OUT / f"bench_{name}.json").write_text(json.dumps(out, indent=1) + "\n")
        print(name, sr, "fields", len(toml), "halfCommit", hex(int.from_bytes(pub[352:384], "big")), prep[f"halfCommit_{role}"])


if __name__ == "__main__":
    main()
