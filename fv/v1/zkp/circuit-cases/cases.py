#!/usr/bin/env python3
"""Runs crafted recordings through the real compiled phone and pair circuits with `nargo execute`.

Local test of our own circuit. All keys are throwaway, generated here, and the issuer is one of them, so a run
that solves says "the circuit's constraints accept this input", not "a real credentialed device would sign it".
Nothing touches a server or a chain.

  server/.venv/bin/python fv/v1/zkp/circuit-cases/cases.py [case ...]    default: all cases

Output: ../logs/circuit-cases.txt (appended) and a summary on stdout.
Compiled circuits come from the zk install in the main README (~/.enconomy/zk/optA/noir), sources are not recompiled unless nargo decides to.
"""
import hashlib, json, os, re, secrets, shutil, subprocess, sys
from pathlib import Path

import numpy as np
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "server"))
from pop import jbl250, popt2, poseidon2 as P2  # noqa: E402

SRC = Path.home() / ".enconomy/zk/optA/noir"
BUILD = HERE / ".build"
NARGO = str(Path.home() / ".enconomy/zk/bin/nargo")
HEAVY = str(ROOT / "research/sound-bound/spikes/zk/tools/heavy.sh")
LOG = HERE.parent / "logs/circuit-cases.txt"
R = P2.R
P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
SR, L, K, DELTA, HM, NS, NP, BAR = 48000, 12000, 193, 96, 31, 12254, 12062, 4474747
WPRE, WPOST = 7200, 12000
CAPTURE = 120000
h = np.array(popt2.RATES[SR]["h"], dtype=np.int64)
assert popt2.RATES[SR]["B"] == BAR


# ---- the arithmetic rule, exact integers. nargo decides; these only pick lags and flag mismatches.
def fir(w):
    return np.convolve(w, h[::-1], "valid")  # y[m] = sum_t h[t] w[m + t]


def self_rule(full, p_self, cI, cQ):
    """first lag in 0..K-1 with BAR*env2 >= big_c, plus I and Q at every lag; a is None if no lag passes."""
    w = full[p_self - DELTA - HM: p_self - DELTA - HM + NS]
    y = fir(w)[: K + L - 1]
    ey = [0]
    for v in y:
        ey.append(ey[-1] + int(v) * int(v))
    cna = int(cI @ cI)
    Is, Qs, a = [], [], None
    for j in range(K):
        seg = w[j + HM: j + HM + L]
        i, q = int(cI @ seg), int(cQ @ seg)
        Is.append(i); Qs.append(q)
        if a is None and (ey[j + L] - ey[j]) * cna - BAR * (i * i + q * q) <= 0:
            a = j
    return a, Is, Qs


def partner_rule(full, a_partner, cI, cQ):
    w = full[a_partner - HM: a_partner - HM + NP]
    y = fir(w)[:L]
    e = sum(int(v) * int(v) for v in y)
    seg = w[HM: HM + L]
    i, q = int(cI @ seg), int(cQ @ seg)
    return BAR * (i * i + q * q) - e * int(cI @ cI) >= 0


# ---- keys and signatures
class Key:
    def __init__(self):
        self.k = ec.generate_private_key(ec.SECP256R1())
        n = self.k.public_key().public_numbers()
        self.x, self.y = n.x.to_bytes(32, "big"), n.y.to_bytes(32, "big")

    def sign(self, msg):
        r, s = decode_dss_signature(self.k.sign(msg, ec.ECDSA(hashes.SHA256())))
        if s > P256_N // 2:  # the bb secp256r1 blackbox rejects high-S
            s = P256_N - s
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def limbs(b):
    return [int.from_bytes(b[:16], "big"), int.from_bytes(b[16:], "big")]


# ---- one session: nonce, issuer, two devices, two pairs of templates
class Session:
    def __init__(self, label):
        self.label = label
        self.nonce = secrets.token_bytes(32)
        self.issuer = Key()
        self.dev = {"A": Key(), "B": Key()}
        seed = hashlib.sha256(b"circuit-cases" + secrets.token_bytes(32)).hexdigest()
        self.code = {}
        for role in "AB":
            ci, cq = popt2.code(jbl250.bed_key(seed, role, 0), role, SR)
            self.code[role] = (np.frombuffer(ci, dtype=np.int8).astype(np.int64),
                               np.frombuffer(cq, dtype=np.int8).astype(np.int64))


def arr(xs):
    return "[" + ", ".join(str(x) for x in xs) + "]"


def qarr(xs):
    return "[" + ", ".join(f'"{x}"' for x in xs) + "]"


def build_phone(ses, role, full, a_self, p_self, a_partner, p_partner, u_lag, Is, Qs, salt=None):
    """Prover.toml text for one phone, and what the pair circuit needs."""
    other = "B" if role == "A" else "A"
    me, you = ses.dev[role], ses.dev[other]
    half = a_partner - a_self if role == "A" else a_self - a_partner
    sod = a_self - p_self
    leaf_s = (p_self - DELTA - HM) // 1024
    leaf_p = (a_partner - HM) // 1024
    levels = P2.rec_levels(full.tolist())
    root = levels[-1][0]
    u8 = {k: (v + 128).tolist() for k, v in zip(("cIs", "cQs", "cIp", "cQp"), ses.code[role] + ses.code[other])}
    code_commit = P2.code_commitment_u8(*[bytes(u8[k]) for k in ("cIs", "cQs", "cIp", "cQp")])
    t = bytearray(311)
    t[:4] = b"POPT"; t[4] = 2; t[5] = ord(role); t[6] = 0
    t[7:39] = ses.nonce
    t[39] = 4; t[40:72] = me.x; t[72:104] = me.y
    t[104] = 4; t[105:137] = you.x; t[137:169] = you.y
    t[169:173] = SR.to_bytes(4, "big")
    t[173:177] = half.to_bytes(4, "big", signed=True)
    t[177:209] = root.to_bytes(32, "big")
    t[233:237] = sod.to_bytes(4, "big", signed=True)
    popc = b"POPC\x02" + bytes(t[5:39]) + bytes(t[177:209])
    assert len(popc) == 71
    t[237:269] = hashlib.sha256(popc).digest()
    t[269:273] = a_self.to_bytes(4, "big")
    t[273:277] = p_partner.to_bytes(4, "big")
    t[277:279] = DELTA.to_bytes(2, "big")
    t[279:311] = code_commit.to_bytes(32, "big")
    exp = (1890000000).to_bytes(8, "big")
    hold = secrets.token_bytes(32)
    cred = b"SBcred3" + me.x + me.y + exp + hold
    salt = secrets.randbits(240) if salt is None else salt
    ix, iy = limbs(ses.issuer.x), limbs(ses.issuer.y)
    u = [j < u_lag for j in range(K)]
    xs = (full[leaf_s * 1024: (leaf_s + 13) * 1024] + 32768).tolist()
    xp = (full[leaf_p * 1024: (leaf_p + 13) * 1024] + 32768).tolist()
    chs = [[[str(c) for c in lv] for lv in P2.rec_path(levels, leaf_s + i)] for i in range(13)]
    chp = [[[str(c) for c in lv] for lv in P2.rec_path(levels, leaf_p + i)] for i in range(13)]
    nh, nl = limbs(ses.nonce)
    toml = (
        f'nonce_hi = "{nh}"\nnonce_lo = "{nl}"\nattempt = 0\nrole_b = {"true" if role == "B" else "false"}\n'
        f'code_commit = "{code_commit}"\nissuer = {qarr(ix + iy)}\nsr = {SR}\nvalid_at = 1790000000\n'
        f"t = {arr(t)}\nsig = {arr(me.sign(bytes(t)))}\nexp = {arr(exp)}\nhold = {arr(hold)}\n"
        f'csig = {arr(ses.issuer.sign(cred))}\nsalt = "{salt}"\n'
        f"c_is = {arr(u8['cIs'])}\nc_qs = {arr(u8['cQs'])}\nc_ip = {arr(u8['cIp'])}\nc_qp = {arr(u8['cQp'])}\n"
        f'xs = {arr(xs)}\nchs = {json.dumps(chs)}\nleaf_s = "{leaf_s}"\n'
        f'xp = {arr(xp)}\nchp = {json.dumps(chp)}\nleaf_p = "{leaf_p}"\n'
        f"ci = {qarr(v % R for v in Is)}\ncq = {qarr(v % R for v in Qs)}\n"
        f"u = {arr('true' if v else 'false' for v in u)}\n"
    )
    commit = P2.half_commit(nh, nl, 0, role == "B", SR, half, salt, me.x, you.x)
    return toml, {"half": half, "salt": salt, "commit": commit, "x": limbs(me.x)}


def build_pair(ses, a, b):
    nh, nl = limbs(ses.nonce)
    return (f'nonce_hi = "{nh}"\nnonce_lo = "{nl}"\nattempt = 0\ncommit_a = "{a["commit"]}"\ncommit_b = "{b["commit"]}"\n'
            f'sr_a = {SR}\nsr_b = {SR}\nhalf_a = "{a["half"] % R}"\nsalt_a = "{a["salt"]}"\n'
            f'half_b = "{b["half"] % R}"\nsalt_b = "{b["salt"]}"\nxa = {qarr(a["x"])}\nxb = {qarr(b["x"])}\n')


# ---- nargo
def setup_build():
    """A private copy of the packages, so the install stays untouched."""
    for pkg in ("oalib", "phone", "pair"):
        d = BUILD / pkg
        (d / "target").mkdir(parents=True, exist_ok=True)
        shutil.copy(SRC / pkg / "Nargo.toml", d / "Nargo.toml")
        shutil.copytree(SRC / pkg / "src", d / "src", dirs_exist_ok=True)
        tgt = SRC / pkg / "target" / f"{pkg}.json"
        if tgt.exists():
            shutil.copy(tgt, d / "target" / f"{pkg}.json")


def nargo(pkg, name, toml):
    d = BUILD / pkg
    (d / f"{name}.toml").write_text(toml)
    res = subprocess.run([HEAVY, f"case-{name}", NARGO, "execute", name, "-p", name, "--silence-warnings"],
                         cwd=d, capture_output=True, text=True)
    text = res.stdout + res.stderr
    (d / f"{name}.toml").unlink()
    (d / "target" / f"{name}.gz").unlink(missing_ok=True)
    ok = "successfully solved" in text
    out = re.search(r"Circuit output: (0x[0-9a-f]+)", text)
    frames = re.findall(r"\n\s*\d+: (\w+)\n", text)
    why = None
    if not ok:
        m = re.search(r"(Failed to solve program: '[^']*'|error: [^\n]*)", text)
        why = (m.group(1) if m else text[-300:].strip()) + (" in " + " < ".join(frames[-3:]) if frames else "")
    return {"ok": ok, "output": int(out.group(1), 16) if out else None, "why": why}


class Report:
    def __init__(self):
        self.rows = []

    def add(self, case, step, res, expect=None, note=""):
        got = "SOLVED" if res["ok"] else "REJECTED"
        flag = "" if expect is None else ("  as expected" if res["ok"] == expect else "  *** UNEXPECTED ***")
        line = f"{case:22} {step:24} {got}{flag}  {note}" + (f"  [{res['why']}]" if res.get("why") else "")
        print(line, flush=True)
        self.rows.append(line)


REP = Report()


def phone(ses, case, role, full, a_self, p_self, a_partner, p_partner, u_lag, Is, Qs, expect=True, note=""):
    toml, info = build_phone(ses, role, full, a_self, p_self, a_partner, p_partner, u_lag, Is, Qs)
    res = nargo("phone", f"{case}_{role}", toml)
    if res["ok"] and res["output"] != info["commit"]:
        note += " *** python half commit differs from circuit output ***"
    REP.add(case, f"phone {role}", res, expect, note + f" half={info['half']}")
    return res, info, toml


def pair(ses, case, a, b, expect, note=""):
    res = nargo("pair", f"{case}_pair", build_pair(ses, a, b))
    fl = 17150 * (a["half"] - b["half"]) / SR
    REP.add(case, "pair", res, expect, note + f" flight={fl:.1f} cm")
    return res


def blank():
    return np.zeros(CAPTURE, dtype=np.int64)


def full_of(x):
    assert len(x) <= 256 * 1024
    f = np.zeros(256 * 1024, dtype=np.int64)
    f[: len(x)] = x
    return f


def noisy_with_codes(ses, role, own_at, partner_at, rng):
    """honest-style capture: background noise, this phone's code and the partner's code at the given frames."""
    other = "B" if role == "A" else "A"
    x = rng.normal(0, 30, CAPTURE)
    x[own_at: own_at + L] += ses.code[role][0] * 120.0
    x[partner_at: partner_at + L] += ses.code[other][0] * 60.0
    return full_of(np.clip(np.round(x), -32768, 32767).astype(np.int64))


def honest(ses, case, role, full, own_at, partner_at, **kw):
    cI, cQ = ses.code[role]
    a, Is, Qs = self_rule(full, own_at, cI, cQ)
    assert a is not None, "honest own code not found"
    a_self = own_at - DELTA + a
    pc = ses.code["B" if role == "A" else "A"]
    assert partner_rule(full, partner_at, *pc), "honest partner code not found"
    return phone(ses, case, role, full, a_self, own_at, partner_at, partner_at - 100, a, Is, Qs, **kw)


# ---- cases
def case_a_control():
    """Honest-style inputs from this harness must solve, and tampered copies must fail."""
    ses = Session("a"); rng = np.random.default_rng(1)
    fa = noisy_with_codes(ses, "A", 24000, 24000 + 45042, rng)
    fb = noisy_with_codes(ses, "B", 24500 + 44947, 24500, rng)
    _, ia, ta = honest(ses, "a_control", "A", fa, 24000, 24000 + 45042)
    _, ib, _ = honest(ses, "a_control", "B", fb, 24500 + 44947, 24500)
    pair(ses, "a_control", ia, ib, True, "near pair")
    # tamper: one opened sample +1 (Merkle), one transcript byte flipped (device signature), wrong nonce (transcript)
    m = re.search(r"\nxs = \[(\d+)", ta)
    REP.add("a_control", "tamper: sample +1", nargo("phone", "a_t1", ta[:m.start(1)] + str(int(m.group(1)) + 1) + ta[m.end(1):]), False)
    m = re.search(r"\nsig = \[(\d+)", ta)
    REP.add("a_control", "tamper: signature byte", nargo("phone", "a_t2", ta[:m.start(1)] + str(int(m.group(1)) ^ 1) + ta[m.end(1):]), False)
    m = re.search(r'nonce_hi = "(\d+)"', ta)
    REP.add("a_control", "tamper: nonce", nargo("phone", "a_t3", ta[:m.start(1)] + str(int(m.group(1)) ^ 1) + ta[m.end(1):]), False)
    # the same phone proofs but honest far halves: the phones pass, pair must refuse
    far = dict(ib); far["half"] = ib["half"] - 2000
    far["commit"] = P2.half_commit(*limbs(ses.nonce), 0, True, SR, far["half"], far["salt"], ses.dev["B"].x, ses.dev["A"].x)
    pair(ses, "a_control", ia, far, False, "far pair (pair circuit alone)")


def silent_phone(ses, case, role, half, p_self=24000, **kw):
    """Digital silence. Lag 0 passes as 0 >= 0, so a_self = p_self - 96; the partner lag is wherever half puts it."""
    full = full_of(blank())
    cI, cQ = ses.code[role]
    a, Is, Qs = self_rule(full, p_self, cI, cQ)
    assert a == 0
    a_self = p_self - DELTA
    a_partner = a_self + half if role == "A" else a_self - half
    if a_partner < HM:  # B's partner lag sits before its own: move the whole window later
        return silent_phone(ses, case, role, half, p_self=p_self + 60000, **kw)
    return phone(ses, case, role, full, a_self, p_self, a_partner, a_partner - 100, 0, Is, Qs, **kw)


def case_b_silence():
    """All-zero recordings on one phone, then checks both windows really are silent."""
    ses = Session("b")
    silent_phone(ses, "b_silence", "A", 45000, note="all zeros")
    silent_phone(ses, "b_silence", "B", 45000, note="all zeros")


def case_c_click():
    """Silence plus one +1 sample, placed to pick lag 50. Needs a template with cna >= 9.1M."""
    for attempt in range(20):
        ses = Session("c")
        cI, cQ = ses.code["A"]
        if int(cI @ cI) >= 9100000:
            break
    a_want, p_self = 50, 24000
    x = blank()
    x[p_self - DELTA - HM + a_want + 8] = 1
    full = full_of(x)
    a, Is, Qs = self_rule(full, p_self, cI, cQ)
    a_self = p_self - DELTA + a
    a_partner = a_self + 45000
    phone(ses, "c_click", "A", full, a_self, p_self, a_partner, a_partner - 100, a, Is, Qs,
          note=f"wanted lag {a_want}, rule found lag {a}, cna={int(cI @ cI)}")


def case_d_tone(n=6):
    """A 500 Hz tone made before any code exists. Each fresh session: does some lag pass on both sides?"""
    nn = np.arange(CAPTURE)
    x = full_of(np.round(10000 * np.sin(2 * np.pi * 500 * nn / SR)).astype(np.int64))
    for i in range(n):
        ses = Session(f"d{i}")
        cI, cQ = ses.code["A"]
        pI, pQ = ses.code["B"]
        p_self = 24000
        a, Is, Qs = self_rule(x, p_self, cI, cQ)
        if a is None:
            print(f"d_tone{i}: no self lag passes in the rule, can't build a witness", flush=True)
            REP.rows.append(f"d_tone{i}: no self lag passes")
            continue
        a_self = p_self - DELTA + a
        cand = [c for c in range(a_self + 44000, a_self + 46000, 7) if partner_rule(x, c, pI, pQ)]
        if not cand:
            print(f"d_tone{i}: self lag {a} passes, no partner lag passes in the rule", flush=True)
            REP.rows.append(f"d_tone{i}: no partner lag passes")
            continue
        ap = cand[len(cand) // 2]
        phone(ses, f"d_tone{i}", "A", x, a_self, p_self, ap, ap - 100, a, Is, Qs,
              note=f"self lag {a}, {len(cand)}/{len(range(a_self + 44000, a_self + 46000, 7))} partner lags pass")


def case_e_fake_near():
    """Far-apart phones, nothing recorded that says so. Do the phone outputs open in pair as NEAR?"""
    # e1: two silent phones, both halves chosen
    ses = Session("e1")
    ra, ia, _ = silent_phone(ses, "e1_both_silent", "A", 45000, note="both silent")
    rb, ib, _ = silent_phone(ses, "e1_both_silent", "B", 45000, note="both silent")
    if ra["ok"] and rb["ok"]:
        pair(ses, "e1_both_silent", ia, ib, None, "chosen halves")
    # e2: B records real codes; A is silent and picks the half that makes the pair look near.
    # B's codes come from a speaker next to B, so B's recording is genuine; B's half says nothing about A's position.
    ses = Session("e2"); rng = np.random.default_rng(2)
    fb = noisy_with_codes(ses, "B", 24500 + 44947, 24500, rng)
    rb, ib, _ = honest(ses, "e2_one_silent", "B", fb, 24500 + 44947, 24500, note="genuine recording")
    ra, ia, _ = silent_phone(ses, "e2_one_silent", "A", ib["half"] + 95, note="silent, half chosen to fit B")
    if ra["ok"] and rb["ok"]:
        pair(ses, "e2_one_silent", ia, ib, None, "one side silent")


CASES = {"a": case_a_control, "b": case_b_silence, "c": case_c_click, "d": case_d_tone, "e": case_e_fake_near}

if __name__ == "__main__":
    setup_build()
    names = sys.argv[1:] or list(CASES)
    for n in names:
        CASES[n]()
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a") as f:
        f.write("\n".join(REP.rows) + "\n")
