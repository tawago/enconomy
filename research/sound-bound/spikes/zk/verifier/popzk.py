"""Session verifier for option A on POPT v2: two per-phone proofs + one pair proof -> NEAR, or a Reject.

This is the ZK counterpart of server/pop/verdict.py combine()/verify_record(): the same session checks, done on
the proofs' public values instead of on plaintext transcripts, plus the links between the three proofs.

  python3 popzk.py pin                                   # write pinned.json: vk sha256 of every oa2t_* circuit
  python3 popzk.py verify <bundle.json> [--nullifiers NA NB]

bundle.json:
  {"session": {"nonce": hex32, "attempt": 0, "code_seed_hex": hex, "valid_at": 1790000000},
   "A": {"circuit": "oa2t_s48", "proof": path}, "B": {...}, "pair": {"circuit": "oa2t_pair", "proof": path}}

What is checked, in order (reason codes mirror server/pop/verdict.py where one applies):
  per phone slot R in (A, B)
    circuit_unknown       the named circuit is not pinned, or its verifying key file's sha256 != the pinned id
    proof_invalid         Spartan2 verification fails, or the public vector has the wrong length
    transcript_mismatch   nonce / attempt != the session's; roleB != the slot (one A, one B); the templates or
                          code_commit != what the verifier derives from the revealed code seed at the proof's sr;
                          sr != the circuit's rate or outside [SR_MIN, SR_MAX]; validAt != the verifier's time
    issuer_unknown        issuer key != the pinned issuer
  pair
    circuit_unknown / proof_invalid   as above
    transcript_mismatch   pair publics != (nonce, attempt, halfCommit_A, halfCommit_B, sr_A, sr_B) taken from the
                          per-phone proofs. This is the link that stops a pair proof over made-up halves.
    missing pair proof    NOT_NEAR, reason "too_far_or_failed": an honest combiner cannot make the pair proof
                          unless -20 < flight < 60 cm, so the verifier cannot tell too_far from impossible_flight.
  human adapters (optional, docs/pop-human-adapters.md): nullifiers are integers (World ID: < 2^254, decimal or
    0x-hex). same_human if equal; else pair_tag = sha256("pop-pair-v1" || min || max), each as 32-byte big-endian.

Not checked here (the caller must): nonce freshness / single use, adapter nullifier uniqueness (UNIQUE(kind,
nullifier)), that the code seed was revealed by the real server for this (session, role, attempt).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZK = HERE.parent
OA2 = ZK / "optionA-v2"
sys.path.insert(0, str(OA2))
PINNED = HERE / "pinned.json"
SR_MIN, SR_MAX = 36000, 96000
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF

# issuer pinned for the spike: the throwaway dev issuer of ../enclave/keys/issuer_dev.pem
DEV_ISSUER = ("9178141b72e5cae00db063dbd38fda4f82a11e1dc8442d2735604719630d99b6",
              "4b75c24fb3128f0646642e3828848d23348f1e08023f5378425a28cffd1885e3")
CIRCUITS = {"oa2t_s48": {"kind": "phone", "sr": 48000, "n_out": 1},
            "oa2t_s44": {"kind": "phone", "sr": 44100, "n_out": 1},
            "oa2t_pair": {"kind": "pair", "n_out": 0}}


class Reject(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


@dataclass
class Policy:
    issuer: tuple = DEV_ISSUER
    pinned: dict = field(default_factory=dict)          # circuit -> vk sha256
    valid_at: int = 1790000000


def vk_path(circuit):
    return OA2 / "keys" / f"{circuit}.vk"


_hash_cache = {}


def vk_sha256(circuit):
    p = vk_path(circuit)
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime_ns)
    if key not in _hash_cache:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""):
                h.update(b)
        _hash_cache[key] = h.hexdigest()
    return _hash_cache[key]


def pin():
    out = {c: vk_sha256(c) for c in CIRCUITS if vk_path(c).exists()}
    PINNED.write_text(json.dumps(out, indent=1))
    return out


def load_policy(**kw):
    return Policy(pinned=json.loads(PINNED.read_text()), **kw)


def inspect(circuit, proof):
    """SNARK-verify with the circuit's vk; return the public vector (strings) or raise proof_invalid."""
    r = subprocess.run([str(OA2 / "oa2zk.sh"), "inspect", circuit, str(proof)], capture_output=True, text=True)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), (r.stdout + r.stderr)[-300:])
    if " ACCEPT " not in line:
        raise Reject("proof_invalid", f"{circuit}: {line[:160]}")
    m = re.search(r"n_public=(\d+) public=\[(.*)\]", line)
    pub = m.group(2).split(",") if m.group(2) else []
    assert len(pub) == int(m.group(1))
    return pub


def check_circuit(circuit, policy, kind):
    meta = CIRCUITS.get(circuit)
    if meta is None or meta["kind"] != kind or circuit not in policy.pinned:
        raise Reject("circuit_unknown", f"{circuit} is not a pinned {kind} circuit")
    if not vk_path(circuit).exists() or vk_sha256(circuit) != policy.pinned[circuit]:
        raise Reject("circuit_unknown", f"{circuit}: verifying key does not match the pinned id")
    return meta


def derive_phone_inputs(session, role, sr, policy):
    """The per-phone public INPUTS the verifier expects, derived from the session and the revealed code seed."""
    import oa_rate as R
    o = "B" if role == "A" else "A"
    tI, tQ = R.templates(session["code_seed_hex"], role, sr)
    pI, pQ = R.templates(session["code_seed_hex"], o, sr)
    cc = R.code_commit(tI, tQ, pI, pQ)
    nonce = bytes.fromhex(session["nonce"])
    vals = [int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big"), session["attempt"],
            1 if role == "B" else 0, int.from_bytes(cc[:16], "big"), int.from_bytes(cc[16:], "big")]
    for t in (tI, tQ, pI, pQ):
        vals += list(t)
    vals += [int(policy.issuer[0], 16), int(policy.issuer[1], 16), sr, policy.valid_at]
    return [str(v % P) for v in vals], len(tI)


def verify_phone(slot, entry, session, policy):
    meta = check_circuit(entry["circuit"], policy, "phone")
    import oa_rate as R
    sr = meta["sr"]
    L = R.params(sr)["L"]
    n_in = 6 + 4 * L + 4
    pub = inspect(entry["circuit"], entry["proof"])
    if len(pub) != meta["n_out"] + n_in:
        raise Reject("proof_invalid", f"{slot}: {len(pub)} public values, want {meta['n_out'] + n_in}")
    outs, got = pub[:meta["n_out"]], pub[meta["n_out"]:]
    nonce = bytes.fromhex(session["nonce"])
    nh, nl = str(int.from_bytes(nonce[:16], "big")), str(int.from_bytes(nonce[16:], "big"))
    if got[0:2] != [nh, nl]:
        raise Reject("transcript_mismatch", f"{slot}: session_nonce")
    if got[2] != str(session["attempt"]):
        raise Reject("transcript_mismatch", f"{slot}: attempt {got[2]} != {session['attempt']}")
    if got[3] != ("1" if slot == "B" else "0"):
        raise Reject("transcript_mismatch", f"{slot} slot holds a role-{'B' if got[3] == '1' else 'A'} proof")
    got_sr = int(got[-2])
    if got_sr != sr or not SR_MIN <= got_sr <= SR_MAX:
        raise Reject("transcript_mismatch", f"{slot}: sample_rate {got_sr}")
    if got[-4:-2] != [str(int(policy.issuer[0], 16)), str(int(policy.issuer[1], 16))]:
        raise Reject("issuer_unknown", f"{slot}: issuer key is not the pinned issuer")
    if got[-1] != str(policy.valid_at):
        raise Reject("transcript_mismatch", f"{slot}: validAt {got[-1]} != {policy.valid_at}")
    exp, _ = derive_phone_inputs(session, slot, sr, policy)
    if got != exp:
        bad = next(i for i, (a, b) in enumerate(zip(got, exp)) if a != b)
        raise Reject("transcript_mismatch", f"{slot}: public input {bad} (code_commit/templates) != derived")
    return {"halfCommit": outs[0], "sr": sr, "circuit": entry["circuit"]}


def nf_int(v) -> int:
    if isinstance(v, int):
        return v
    v = str(v).strip()
    return int(v, 16) if v.lower().startswith("0x") else int(v)


def pair_tag(na, nb) -> str:
    a, b = sorted((nf_int(na), nf_int(nb)))
    return hashlib.sha256(b"pop-pair-v1" + a.to_bytes(32, "big") + b.to_bytes(32, "big")).hexdigest()


def verify_session(bundle: dict, policy: Policy, nullifiers=None) -> dict:
    """-> {"verdict": "NEAR"|"NOT_NEAR", "reason", "sample_rates", "pair_tag", "circuits"}; raises Reject."""
    session = bundle["session"]
    ph = {r: verify_phone(r, bundle[r], session, policy) for r in "AB"}
    tag = None
    if nullifiers is not None:
        na, nb = nullifiers
        if nf_int(na) == nf_int(nb):
            raise Reject("same_human", "the two adapter nullifiers are equal")
        tag = pair_tag(na, nb)
    base = {"sample_rates": {r: ph[r]["sr"] for r in "AB"}, "pair_tag": tag,
            "circuits": {r: ph[r]["circuit"] for r in "AB"}}
    if not bundle.get("pair"):
        return {"verdict": "NOT_NEAR", "reason": "too_far_or_failed", **base}
    check_circuit(bundle["pair"]["circuit"], policy, "pair")
    pub = inspect(bundle["pair"]["circuit"], bundle["pair"]["proof"])
    if len(pub) != 7:
        raise Reject("proof_invalid", f"pair: {len(pub)} public values, want 7")
    nonce = bytes.fromhex(session["nonce"])
    want = [str(int.from_bytes(nonce[:16], "big")), str(int.from_bytes(nonce[16:], "big")), str(session["attempt"]),
            ph["A"]["halfCommit"], ph["B"]["halfCommit"], str(ph["A"]["sr"]), str(ph["B"]["sr"])]
    names = ["nonceHi", "nonceLo", "attempt", "commitA", "commitB", "srA", "srB"]
    for n, g, w in zip(names, pub, want):
        if g != w:
            raise Reject("transcript_mismatch", f"pair {n} != the per-phone proofs'")
    base["circuits"]["pair"] = bundle["pair"]["circuit"]
    return {"verdict": "NEAR", "reason": None, **base}


def main():
    a = sys.argv[1:]
    if a[0] == "pin":
        print(json.dumps(pin(), indent=1))
        return 0
    if a[0] == "verify":
        bundle = json.loads(Path(a[1]).read_text())
        nfs = a[a.index("--nullifiers") + 1: a.index("--nullifiers") + 3] if "--nullifiers" in a else None
        try:
            print(json.dumps(verify_session(bundle, load_policy(), nfs)))
            return 0
        except Reject as e:
            print(json.dumps({"verdict": "REJECT", "reason": e.reason, "detail": e.detail}))
            return 1


if __name__ == "__main__":
    sys.exit(main())
