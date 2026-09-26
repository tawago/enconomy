#!/usr/bin/env python3
"""Real POPT v2 fixture -> Prover.toml for the Noir option A port (phone, phone_pub, pair).

usage (a python with numpy + soundfile; scipy only for 44.1 kHz captures):
  PY=python-with-numpy
  $PY gen_inputs.py 180ca04b_48k A NOIR_BUILD_DIR          # NARGO=... (for the helper)

What is real and what is recomputed:
  real   : the audio (capture regenerated from the field WAV exactly as build_fixtures_popt2.py did, checked
           sample for sample against the circom witness), templates, claimed curve I/Q, arrival selector u,
           leaf indices, every transcript field except the two hashes, SBcred3 + the issuer signature, salt.
  changed: rec_root (Poseidon7/P-256 -> Poseidon2/BN254 tree over the same capture) and, for the onchain
           variant, code_commit (SHA-256 of the templates -> Poseidon2 commitment). The transcript is then
           re-signed by the SAME Secure Enclave key (enclave/sesign, keys/<role>.seblob) of this Mac.
  ECDSA s values are normalized to low-S (the bb secp256r1 blackbox rejects high-S; anyone can do this).
Inputs are read only from research/sound-bound/spikes/zk/{fixtures,optionA-v2/inputs,enclave} and the
fieldtest session WAVs.
"""
import base64
import json
import os
import pathlib
import re
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[4]
ZK = ROOT / "research/sound-bound/spikes/zk"
sys.path.insert(0, str(ZK / "enclave"))
import emulate as em  # noqa: E402

R_BN = 21888242871839275222246405745257275088548364400416034343698204186575808495617
P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
TAG_HALF = 8

fx_name, role, out = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3])
NARGO = os.environ.get("NARGO", "nargo")
fx = json.loads((ZK / "fixtures/popt_v2" / f"{fx_name}.json").read_text())
wi = json.loads((ZK / "optionA-v2/inputs" / f"popt2_{fx_name}_{role}.input.json").read_text())
other = "B" if role == "A" else "A"
r = fx["roles"][role]
sr = r["sample_rate"]
assert sr == 48000, "the Noir port is compiled for 48 kHz"


def sgn_p(v):  # P-256-field element -> signed int
    v = int(v)
    return v - P256_P if v > P256_P // 2 else v


def fbn(v):  # signed int -> BN254 field decimal string
    return str(int(v) % R_BN)


def arr(xs):
    return "[" + ", ".join(xs) + "]"


def q(xs):
    return arr('"%s"' % x for x in xs)


# ---- capture, checked against the circom witness
sess = em.session_dir(fx["field_session_id"][:8])
cap, _, _ = em.capture(sess, role, sr)
cap = np.asarray(cap, dtype=np.int64)
assert len(cap) == r["capture_frames"], len(cap)
full = np.zeros(256 * 1024, dtype=np.int64)
full[: len(cap)] = cap
leaf_s, leaf_p = int(wi["leafS"]), int(wi["leafP"])
xs = [sgn_p(v) for row in wi["xs"] for v in row]
xp = [sgn_p(v) for row in wi["xp"] for v in row]
assert xs == list(full[leaf_s * 1024:(leaf_s + 13) * 1024]), "self leaves differ from the regenerated capture"
assert xp == list(full[leaf_p * 1024:(leaf_p + 13) * 1024]), "partner leaves differ from the regenerated capture"
tmpl = {k: [sgn_p(v) for v in wi[k]] for k in ("cIs", "cQs", "cIp", "cQp")}
for k, v in tmpl.items():
    assert all(-128 <= x <= 127 for x in v), k
u8t = {k: [str(x + 128) for x in v] for k, v in tmpl.items()}

# ---- helper: Poseidon2 tree + code commitment + both half commitments
nonce = bytes.fromhex(fx["session_nonce"])
nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")


def hc_in(rl):
    x = fx["roles"][rl]
    o = "B" if rl == "A" else "A"
    ks, kp = bytes.fromhex(x["pubkey"][2:66]), bytes.fromhex(fx["roles"][o]["pubkey"][2:66])
    return [nh, nl, fx["attempt"], 1 if rl == "B" else 0, x["sample_rate"], x["half"], int(x["salt_dev"], 16),
            int.from_bytes(ks[:16], "big"), int.from_bytes(ks[16:], "big"),
            int.from_bytes(kp[:16], "big"), int.from_bytes(kp[16:], "big")]


hdir = out / "helper"
(hdir / "Prover.toml").write_text(
    "cap = " + arr(str(int(v) + 32768) for v in full) + "\n"
    + "".join(f"{k} = {arr(u8t[n])}\n" for k, n in (("c_is", "cIs"), ("c_qs", "cQs"), ("c_ip", "cIp"), ("c_qp", "cQp")))
    + "hc_a = " + q(fbn(v) for v in hc_in("A")) + "\n"
    + "hc_b = " + q(fbn(v) for v in hc_in("B")) + "\n")
res = subprocess.run([NARGO, "execute"], cwd=hdir, capture_output=True, text=True)
if res.returncode:
    sys.exit(res.stdout + res.stderr)
nums = [int(v, 16) for v in re.findall(r"0x[0-9a-fA-F]+", res.stdout.split("output:", 1)[1])]
assert len(nums) == 344, len(nums)
lv, code_p2, hcA, hcB = nums[:341], nums[341], nums[342], nums[343]
levels, base, n = [], 0, 256
for _ in range(5):
    levels.append(lv[base: base + n])
    base += n
    n //= 4
root = levels[4][0]


def path(idx):
    out_, i = [], idx
    for l in range(4):
        b = (i // 4) * 4
        out_.append([levels[l][b + k] for k in range(4)])
        i //= 4
    return out_


chs = [path(leaf_s + i) for i in range(13)]
chp = [path(leaf_p + i) for i in range(13)]

# ---- transcripts, re-signed by the Secure Enclave key of this role
t0 = bytearray(base64.b64decode(r["transcript_b64"]))
assert len(t0) == 311


def se_sign(msg):
    j = json.loads(subprocess.run([str(ZK / "enclave/sesign"), "sign", str(ZK / f"enclave/keys/{role}.seblob"), msg.hex()],
                                  capture_output=True, text=True, check=True).stdout)
    return lows(bytes.fromhex(j["r"]) + bytes.fromhex(j["s"]))


def lows(sig):
    s = int.from_bytes(sig[32:], "big")
    if s > P256_N // 2:
        s = P256_N - s
    return sig[:32] + s.to_bytes(32, "big")


t_on = bytearray(t0)
t_on[177:209] = root.to_bytes(32, "big")
t_on[279:311] = code_p2.to_bytes(32, "big")
t_pub = bytearray(t0)
t_pub[177:209] = root.to_bytes(32, "big")
sig_on, sig_pub = se_sign(bytes(t_on)), se_sign(bytes(t_pub))
cred_sig = lows(bytes.fromhex(r["cred_sig_r_hex"] + r["cred_sig_s_hex"]))
cred = bytes.fromhex(r["cred_hex"])
assert cred[:7] == b"SBcred3" and cred[7:71] == bytes(t0[40:104])
ix, iy = fx["issuer"]["pub_x"], fx["issuer"]["pub_y"]
issuer = [str(int(h, 16)) for h in (ix[:32], ix[32:], iy[:32], iy[32:])]
cc = bytes.fromhex(r["code_commit"])


def common(t, sig):
    return (f"nonce_hi = \"{nh}\"\nnonce_lo = \"{nl}\"\nattempt = {fx['attempt']}\nrole_b = {'true' if role == 'B' else 'false'}\n"
            f"issuer = {q(issuer)}\nsr = {sr}\nvalid_at = 1790000000\n"
            f"t = {arr(str(b) for b in t)}\nsig = {arr(str(b) for b in sig)}\n"
            f"exp = {arr(str(b) for b in cred[71:79])}\nhold = {arr(str(b) for b in cred[79:111])}\n"
            f"csig = {arr(str(b) for b in cred_sig)}\nsalt = \"{int(r['salt_dev'], 16)}\"\n"
            f"xs = {arr(str(v + 32768) for v in xs)}\nchs = {json.dumps([[[str(c) for c in l] for l in p] for p in chs])}\n"
            f"leaf_s = \"{leaf_s}\"\nxp = {arr(str(v + 32768) for v in xp)}\n"
            f"chp = {json.dumps([[[str(c) for c in l] for l in p] for p in chp])}\nleaf_p = \"{leaf_p}\"\n"
            f"ci = {q(fbn(sgn_p(v)) for v in wi['I'])}\ncq = {q(fbn(sgn_p(v)) for v in wi['Q'])}\n"
            f"u = {arr('true' if v == '1' else 'false' for v in wi['u'])}\n")


(out / "phone" / "Prover.toml").write_text(
    common(t_on, sig_on) + f"code_commit = \"{code_p2}\"\n"
    + "".join(f"{k} = {arr(u8t[n])}\n" for k, n in (("c_is", "cIs"), ("c_qs", "cQs"), ("c_ip", "cIp"), ("c_qp", "cQp"))))
(out / "phone_pub" / "Prover.toml").write_text(
    common(t_pub, sig_pub)
    + f"code_hi = \"{int.from_bytes(cc[:16], 'big')}\"\ncode_lo = \"{int.from_bytes(cc[16:], 'big')}\"\n"
    + "".join(f"{k} = {q(fbn(x) for x in tmpl[n])}\n" for k, n in (("c_is", "cIs"), ("c_qs", "cQs"), ("c_ip", "cIp"), ("c_qp", "cQp"))))

# ---- FIR-lever variants (phone_opt, phone_opt_popc): the prover also supplies the FIR outputs, offset by 2^25
h = json.loads((ZK / "optionA-v2/circuits/main/oa2t_s48.json").read_text())["fir"]
DELTA, HM, K, L = 96, 31, 193, 12000
t_dec = bytes(t_on)
a_self = int.from_bytes(t_dec[269:273], "big")
sod = int.from_bytes(t_dec[233:237], "big", signed=True)
half_s = int.from_bytes(t_dec[173:177], "big", signed=True)
p_self = a_self - sod
a_part = a_self + (half_s if role == "A" else -half_s)
ws = full[p_self - DELTA - HM: p_self - DELTA - HM + (K + L - 1 + 2 * HM)]
wp = full[a_part - HM: a_part - HM + (L + 2 * HM)]
ys = np.convolve(ws, np.array(h[::-1], dtype=np.int64), mode="valid")
yp = np.convolve(wp, np.array(h[::-1], dtype=np.int64), mode="valid")
assert len(ys) == K + L - 1 and len(yp) == L
assert np.abs(ys).max() < 2 ** 25 and np.abs(yp).max() < 2 ** 25
yl = f"ys = {q(str(int(v) + 2 ** 25) for v in ys)}\nyp = {q(str(int(v) + 2 ** 25) for v in yp)}\n"
base_on = (out / "phone" / "Prover.toml").read_text()
if (out / "phone_opt").exists():
    (out / "phone_opt" / "Prover.toml").write_text(base_on + yl)
if (out / "phone_opt_popc").exists():
    popc = b"POPC\x02" + bytes(t_on[5:39]) + bytes(t_on[177:209])
    assert len(popc) == 71
    (out / "phone_opt_popc" / "Prover.toml").write_text(base_on + yl + f"popc_sig = {arr(str(b) for b in se_sign(popc))}\n")
A, B = fx["roles"]["A"], fx["roles"]["B"]


def xlimbs(rl):
    k = bytes.fromhex(fx["roles"][rl]["pubkey"][2:66])
    return [str(int.from_bytes(k[:16], "big")), str(int.from_bytes(k[16:], "big"))]


(out / "pair" / "Prover.toml").write_text(
    f"nonce_hi = \"{nh}\"\nnonce_lo = \"{nl}\"\nattempt = {fx['attempt']}\ncommit_a = \"{hcA}\"\ncommit_b = \"{hcB}\"\n"
    f"sr_a = {A['sample_rate']}\nsr_b = {B['sample_rate']}\nhalf_a = \"{fbn(A['half'])}\"\nsalt_a = \"{int(A['salt_dev'], 16)}\"\n"
    f"half_b = \"{fbn(B['half'])}\"\nsalt_b = \"{int(B['salt_dev'], 16)}\"\nxa = {q(xlimbs('A'))}\nxb = {q(xlimbs('B'))}\n")
json.dump({"fixture": fx_name, "role": role, "rec_root_p2": hex(root), "code_commit_p2": hex(code_p2),
           "halfCommit_A": hex(hcA), "halfCommit_B": hex(hcB), "leaf_s": leaf_s, "leaf_p": leaf_p,
           "transcript_onchain": bytes(t_on).hex(), "sig_onchain": sig_on.hex(),
           "transcript_faithful": bytes(t_pub).hex(), "sig_faithful": sig_pub.hex(),
           "a_self": r["a_self"], "p_self": r["p_self"], "a_partner": r["a_partner"], "half": r["half"]},
          open(out / f"prep_{fx_name}_{role}.json", "w"), indent=1)
print("ok", fx_name, role, "root", hex(root), "code", hex(code_p2), "hcA", hex(hcA), "hcB", hex(hcB))
