#!/usr/bin/env python3
"""Real POPT v2 fixture -> Prover.toml for half (A, B) and pair.

usage: gen_real.py FIXTURE.json NOIR_DIR [--cred real|bn] [--lows] [--now N] [--tamper-a]
  --cred real : use the fixture's SBcred3 bytes + issuer sig as-is (holder_commit = Poseidon7 over P-256 Fp)
  --cred bn   : re-issue SBcred3-bn (same device key, same expiry, holder_commit = Poseidon2_bn254(holder_secret_dev))
                signed by the same dev issuer key (enclave/keys/issuer_dev.pem, read only). Needs NARGO for hashhelper.
  --lows      : normalize every ECDSA s to low-S (s -> n - s)
  --tamper-a  : flip one byte of A's transcript (half field) after signing
Transcripts and device signatures are always the fixture's real bytes.
"""
import base64, json, os, subprocess, sys, pathlib, re, argparse

N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
ZK = pathlib.Path(__file__).resolve().parents[5] / "research/sound-bound/spikes/zk"
ISSUER_PEM = ZK / "enclave/keys/issuer_dev.pem"

ap = argparse.ArgumentParser()
ap.add_argument("fixture"); ap.add_argument("noir")
ap.add_argument("--cred", default="real"); ap.add_argument("--lows", action="store_true")
ap.add_argument("--now", default="1790400000"); ap.add_argument("--tamper-a", action="store_true")
a = ap.parse_args()
d = json.load(open(a.fixture)); noir = pathlib.Path(a.noir)


def lows(sig: bytes) -> bytes:
    s = int.from_bytes(sig[32:], "big")
    if a.lows and s > N // 2: s = N - s
    return sig[:32] + s.to_bytes(32, "big")


def der_to_raw(der: bytes) -> bytes:
    # SEQ { INT r, INT s }
    i = 2; out = []
    for _ in range(2):
        assert der[i] == 2; l = der[i + 1]; out.append(int.from_bytes(der[i + 2:i + 2 + l], "big")); i += 2 + l
    return out[0].to_bytes(32, "big") + out[1].to_bytes(32, "big")


def issuer_sign(msg: bytes) -> bytes:
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(ISSUER_PEM), "-binary"], input=msg,
                         capture_output=True, check=True).stdout
    return der_to_raw(der)


def poseidon2_bn(x: int) -> bytes:
    hh = pathlib.Path(__file__).parent / "hashhelper"
    (hh / "Prover.toml").write_text(f's = "{hex(x)}"\n')
    out = subprocess.run([os.environ.get("NARGO", "nargo"), "execute"], cwd=hh, capture_output=True, text=True, check=True).stdout
    m = re.search(r"output:\s*\[(.*?)\]", out, re.S)
    b = [int(v, 0) for v in m.group(1).replace('"', '').split(",")]
    assert len(b) == 32, out
    return bytes(b)


def side(r):
    x = d["roles"][r]
    t = bytearray(base64.b64decode(x["transcript_b64"])); st = base64.b64decode(x["sig_b64"])
    assert len(t) == 311 and len(st) == 64
    hs = int(x["holder_secret_dev"], 16)
    if a.cred == "real":
        c = bytes.fromhex(x["cred_hex"]); cs = bytes.fromhex(x["cred_sig_r_hex"] + x["cred_sig_s_hex"])
    else:
        c = b"SBcred3" + bytes(t[40:104]) + int(x["cred_expiry_unix"]).to_bytes(8, "big") + poseidon2_bn(hs)
        cs = issuer_sign(c)
    assert len(c) == 111
    if a.tamper_a and r == "A": t[175] ^= 0x01
    arr = lambda b: "[" + ", ".join(str(v) for v in b) + "]"
    return dict(t=arr(t), s=arr(lows(st)), c=arr(c), cs=arr(lows(cs)), hs=hex(hs))


ix, iy = d["issuer"]["pub_x"], d["issuer"]["pub_y"]
pub = (f'issuer = ["0x{ix[:32]}", "0x{ix[32:]}", "0x{iy[:32]}", "0x{iy[32:]}"]\nnow = "{a.now}"\n'
       'scope = "0x5afe"\ncontext = "0x0123456789abcdef"\n')
A, B = side("A"), side("B")
h = lambda s: f'transcript = {s["t"]}\nsig_t = {s["s"]}\ncred = {s["c"]}\nsig_c = {s["cs"]}\nholder_secret = "{s["hs"]}"\n'
(noir / "half/Prover.toml").write_text(h(A) + pub)
(noir / "half/ProverB.toml").write_text(h(B) + pub)
(noir / "pair/Prover.toml").write_text(
    f't_a = {A["t"]}\ns_a = {A["s"]}\nc_a = {A["c"]}\ncs_a = {A["cs"]}\nhs_a = "{A["hs"]}"\n'
    f't_b = {B["t"]}\ns_b = {B["s"]}\nc_b = {B["c"]}\ncs_b = {B["cs"]}\nhs_b = "{B["hs"]}"\n' + pub)
print("ok", d["name"], d["expect"]["verdict"], "flight_cm", d["expect"]["flight_cm"], "cred", a.cred, "lows", a.lows)
