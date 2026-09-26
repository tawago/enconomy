#!/usr/bin/env python3
"""Tamper cases for the Noir phone circuit: each writes phone/Prover_<case>.toml from the honest Prover.toml and runs
`nargo execute` (expect failure, i.e. no witness and therefore no proof).

usage: NARGO=... python3 tamper.py NOIR_BUILD_DIR [ROLE]
  sample        one opened self sample +1                                  -> Merkle path (leaf hash) fails
  curve         claimed I_0 + 1                                            -> Freivalds identity fails
  u_later       arrival selector one lag later, transcript unchanged       -> sum(u) != a_self - p_self + delta
  resign_late   compromised app re-signs a_self' = p_self + delta (sod' = delta, same p_self and a_partner),
                Secure Enclave signature valid                             -> self rule (an earlier lag >= bar)
  resign_early  compromised app re-signs a_partner' = a_partner - 100 (half adjusted), SE signature valid
                                                                           -> partner bar fails
  nonce         public nonce_hi xor 1                                      -> transcript nonce check fails
  half          signed half +30 in the witness bytes, not re-signed        -> ECDSA (device signature) fails
  sr            public sr = 44100 on the 48 kHz circuit                    -> sr check fails
  swap_role     public role_b flipped, same signed bytes                   -> role byte check fails
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[4]
ZK = ROOT / "research/sound-bound/spikes/zk"
P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
R_BN = 21888242871839275222246405745257275088548364400416034343698204186575808495617
B = pathlib.Path(sys.argv[1])
ROLE = sys.argv[2] if len(sys.argv) > 2 else "A"
NARGO = os.environ.get("NARGO", "nargo")
PH = B / "phone"
base = tomllib.loads((PH / "Prover.toml").read_text())
DELTA, K = 96, 193


def dump(d):
    def v(x):
        if isinstance(x, bool):
            return "true" if x else "false"
        if isinstance(x, int):
            return str(x)
        if isinstance(x, str):
            return json.dumps(x)
        return "[" + ", ".join(v(y) for y in x) + "]"
    return "".join(f"{k} = {v(x)}\n" for k, x in d.items())


def sign(t):
    j = json.loads(subprocess.run([str(ZK / "enclave/sesign"), "sign", str(ZK / f"enclave/keys/{ROLE}.seblob"), bytes(t).hex()],
                                  capture_output=True, text=True, check=True).stdout)
    s = int(j["s"], 16)
    s = P256_N - s if s > P256_N // 2 else s
    return list(bytes.fromhex(j["r"])) + list(s.to_bytes(32, "big"))


def u32(t, off):
    return int.from_bytes(bytes(t[off:off + 4]), "big")


def i32(t, off):
    v = u32(t, off)
    return v - (1 << 32) if v >= 1 << 31 else v


def put_i32(t, off, v):
    t[off:off + 4] = list((v % (1 << 32)).to_bytes(4, "big"))


def case(name):
    d = json.loads(json.dumps(base))
    t = d["t"]
    a_self, sod, half = u32(t, 269), i32(t, 233), i32(t, 173)
    p_self = a_self - sod
    sgn = 1 if ROLE == "A" else -1
    a_part = a_self + sgn * half
    if name == "sample":
        d["xs"][1024 + 500] += 1
    elif name == "curve":
        d["ci"][0] = str((int(d["ci"][0]) + 1) % R_BN)
    elif name == "u_later":
        j = sum(d["u"])
        d["u"][j] = True
    elif name == "resign_late":
        a2 = p_self + DELTA
        if a2 == a_self:
            return None
        t[269:273] = list(a2.to_bytes(4, "big"))
        put_i32(t, 233, a2 - p_self)
        put_i32(t, 173, sgn * (a_part - a2))
        d["sig"] = sign(t)
        d["u"] = [k < a2 - (p_self - DELTA) for k in range(K)]
    elif name == "resign_early":
        a_p2 = a_part - 100
        put_i32(t, 173, sgn * (a_p2 - a_self))
        d["sig"] = sign(t)
        assert (a_p2 - 31) // 1024 == int(d["leaf_p"]), "partner leaf would change"
    elif name == "nonce":
        d["nonce_hi"] = str(int(d["nonce_hi"]) ^ 1)
    elif name == "half":
        put_i32(t, 173, half + 30)
    elif name == "sr":
        d["sr"] = 44100
    elif name == "swap_role":
        d["role_b"] = not d["role_b"]
    else:
        raise SystemExit(name)
    (PH / f"Prover_{name}.toml").write_text(dump(d))
    r = subprocess.run([NARGO, "execute", "-p", f"Prover_{name}", f"w_{name}"], cwd=PH, capture_output=True, text=True)
    txt = r.stdout + r.stderr
    loc = re.findall(r"(?:lib|main)\.nr:\d+", txt)
    msg = re.search(r"error: (.*)", txt)
    return ("ACCEPTED (witness solved)" if r.returncode == 0 else
            "rejected at %s (%s)" % (loc[0] if loc else "?", msg.group(1).strip() if msg else txt.strip().splitlines()[-1]))


for c in (sys.argv[3:] or ["sample", "curve", "u_later", "resign_late", "resign_early", "nonce", "half", "sr", "swap_role"]):
    print(f"{c:13s} {case(c)}", flush=True)
