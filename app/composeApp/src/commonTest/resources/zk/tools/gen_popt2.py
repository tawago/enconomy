"""Writes the POPT v2 parity fixtures (commonTest/resources/zk/popt2/<s8>.json + .bin) from the spike python.

Run: $PY gen_popt2.py   ($PY = research/proximity-echo/.venv/bin/python3). Reads research/ only.
Needs the spike's optionA-v2/build/popt2 captures (gitignored there, present on the dev Mac).

Per session: the 48k fixture (both roles) and, for MIX sessions, the mix fixture (A = the same 48 kHz
capture, B at 44.1 kHz). Expected values are the fixture's signed ones, re-derived here with
oa_rate.earliest / rectree so a stale fixture fails loudly. Size is kept down by storing only what the
rule reads: per capture, int16 crops [window lo - 31, arrival + L + 31] (leaf aligned) for the fixture
window and the app window [p - WPRE, p + WPOST), plus every leaf hash of the tree. Captures that are
already in the test resources are referenced instead (zk/rec_*.json full captures, dsp/*_k0.json
segments = capture[12000:98400]).

.bin = concatenated blobs (int16 LE crops, int8 codes, 32-byte BE leaf hashes); the JSON gives offsets.
"""
import base64
import json
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True  # nothing lands in research/
HERE = Path(__file__).resolve().parent
RES = HERE.parents[1]
OUT = RES / "zk" / "popt2"
REPO = HERE.parents[6]
ZK = REPO / "research/sound-bound/spikes/zk"
OA2 = ZK / "optionA-v2"
sys.path.insert(0, str(OA2))
sys.path.insert(0, str(OA2 / "poseidon7"))
import oa_rate as R  # noqa: E402
import rectree  # noqa: E402

SESSIONS = ["180ca04b", "2940913c", "2dc2eb59", "7711d899", "9afb91c6", "b2a5f86d", "b550cf12", "b9e4dd4b",
            "d1ee4fb0", "d283370f", "ef0b6e11", "f3ff0ee8"]
MIX = ["180ca04b", "2940913c", "7711d899", "b550cf12"]
REC = {"180ca04b_48k_A": "rec_180ca04b_48k_A.json", "180ca04b_48k_B": "rec_180ca04b_48k_B.json",
       "2940913c_mix_B": "rec_2940913c_mix_B.json"}
DSP = {"2dc2eb59", "b9e4dd4b", "d1ee4fb0", "f3ff0ee8"}
DSP_OFF = 12000
HM = R.HM


class Blob:
    def __init__(self):
        self.parts, self.n = [], 0

    def add(self, b: bytes) -> dict:
        o = {"off": self.n, "len": len(b)}
        self.parts.append(b)
        self.n += len(b)
        return o


def fixture(s8, mode):
    return json.loads((ZK / "fixtures/popt_v2" / f"{s8}_{mode}.json").read_text())


def pcm_of(o, src):
    if src["src"] == "rec":
        d = json.loads((RES / "zk" / src["file"]).read_text())
        return np.frombuffer(base64.b64decode(d["pcm16_b64"]), "<i2")
    d = json.loads((RES / "dsp" / src["file"]).read_text())
    return np.frombuffer(base64.b64decode(d["listeners"][src["role"]]["segment_pcm16_b64"]), "<i2")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for s8 in SESSIONS:
        blob = Blob()
        modes = ["48k"] + (["mix"] if s8 in MIX else [])
        fx = {m: fixture(s8, m) for m in modes}
        seed = fx["48k"]["seed_hex"]
        caps, uses = {}, {}
        for m in modes:
            for r in "AB":
                x = fx[m]["roles"][r]
                key = f"48k_{r}" if (m == "mix" and r == "A") else f"{m}_{r}"
                cap = np.load(ZK / x["capture_npy"])
                if key in caps:
                    assert np.array_equal(caps[key]["x"], cap), (s8, m, r)
                else:
                    caps[key] = {"x": cap, "sr": x["sample_rate"], "root": x["rec_root"], "tree": x["tree_json"]}
                uses.setdefault(key, []).append((m, r))
        codes = {}
        for sr in sorted({c["sr"] for c in caps.values()}):
            codes[str(sr)] = {}
            for e in "AB":
                cI, cQ = R.templates(seed, e, sr)
                codes[str(sr)][e] = {"cI": blob.add(np.asarray(cI, np.int8).tobytes()),
                                     "cQ": blob.add(np.asarray(cQ, np.int8).tobytes()), "n": len(cI)}
        roles = {m: {} for m in modes}
        need = {k: [] for k in caps}
        for key, us in uses.items():
            c = caps[key]
            x, sr = c["x"], c["sr"]
            P = R.params(sr)
            L = P["L"]
            for m, r in us:
                f = fx[m]["roles"][r]
                o = "B" if r == "A" else "A"
                out = {"capture": key}
                for kind, em, win, p in (("self", r, f["search_self"], f["p_self"]),
                                         ("partner", o, f["search_partner"], f["p_partner"])):
                    cI, cQ = R.templates(seed, em, sr)
                    a, sc, *_ = R.earliest(x, cI, cQ, win[0], win[1], sr)
                    want = f["a_self"] if kind == "self" else f["a_partner"]
                    assert a == want, (s8, m, r, kind, a, want)
                    lo2, hi2 = p - P["WPRE"], p + P["WPOST"]
                    a2, sc2, *_ = R.earliest(x, cI, cQ, lo2, hi2, sr)
                    assert a2 is not None
                    out[kind] = {"window": win, "arrival": a, "score": sc, "app_window": [lo2, hi2],
                                 "app_arrival": a2, "app_score": sc2, "p": p}
                    need[key].append((min(win[0], lo2) - HM, max(a, a2) + L + HM))
                for k in ("sample_rate", "half", "a_self", "a_partner", "p_self", "p_partner", "self_os_delta",
                          "delta", "rec_root", "code_commit", "transcript_b64", "commit_b64", "pubkey"):
                    out[k] = f[k]
                roles[m][r] = out
        capo = {}
        for key, c in caps.items():
            x = c["x"]
            n = len(x)
            lv = rectree.load(json.loads((ZK / c["tree"]).read_text()))
            assert rectree.root(lv) == int(c["root"], 16)
            leaves = b"".join(int(lv[0][i]).to_bytes(32, "big") for i in sorted(lv[0]))
            co = {"sr": c["sr"], "frames": n, "rec_root": c["root"], "leaves": blob.add(leaves)}
            rkey = f"{s8}_{key}"
            if rkey in REC:
                co["source"] = {"src": "rec", "file": REC[rkey]}
                y = pcm_of(co, co["source"])
                assert np.array_equal(y, x)
            elif s8 in DSP and key.startswith("48k"):
                co["source"] = {"src": "dsp", "file": f"{s8}_k0.json", "role": key[-1], "offset": DSP_OFF}
                y = pcm_of(co, co["source"])
                assert np.array_equal(y, x[DSP_OFF: DSP_OFF + len(y)])
                for lo, hi in need[key]:
                    assert DSP_OFF <= lo and hi <= DSP_OFF + len(y), (s8, key, lo, hi)
            else:
                spans = sorted((max(0, lo // 1024 * 1024), min(n, -(-hi // 1024) * 1024)) for lo, hi in need[key])
                merged = []
                for a, b in spans:
                    if merged and a <= merged[-1][1]:
                        merged[-1][1] = max(merged[-1][1], b)
                    else:
                        merged.append([a, b])
                co["source"] = {"src": "crops", "crops": [
                    {"start": a, **blob.add(x[a:b].astype("<i2").tobytes())} for a, b in merged]}
            capo[key] = co
        name = f"{s8}"
        (OUT / f"{name}.bin").write_bytes(b"".join(blob.parts))
        doc = {"session": s8, "seed_hex": seed, "attempt": 0,
               "modes": {m: {"session_nonce": fx[m]["session_nonce"], "roles": roles[m], "expect": fx[m]["expect"]}
                         for m in modes},
               "captures": capo, "codes": codes, "bin": f"{name}.bin"}
        (OUT / f"{name}.json").write_text(json.dumps(doc, indent=1) + "\n")
        sz = blob.n + (OUT / f"{name}.json").stat().st_size
        total += sz
        print(f"{s8}: {modes} {sz / 1e3:.0f} kB", flush=True)
    (OUT / "index.json").write_text(json.dumps({"sessions": SESSIONS}) + "\n")
    print(f"total {total / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
