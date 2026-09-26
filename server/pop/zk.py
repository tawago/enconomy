"""Option A proofs: per-phone public vector, SNARK verification, proving-key files.

Port of the checks in research/sound-bound/spikes/zk/verifier/popzk.py (verify_phone), with the public inputs taken
from what this server holds instead of a revealed seed:

  public = [halfCommit, nonceHi, nonceLo, attempt, roleB, codeHi, codeLo, cIs[L], cQs[L], cIp[L], cQp[L],
            issuerX, issuerY, sr, validAt]                                     1 + 6 + 4L + 4 values, mod p
  halfCommit = Poseidon7.sponge16(8, [nonceHi, nonceLo, attempt, roleB, sr, half mod p, salt, X_self, X_partner])

nonce, attempt, role, sr, half and both keys come from the signed POPT v2, the codes from the server's own bed keys
(the ones it sent), issuer from its key, validAt = t0_ms // 1000 of the attempt, salt from the upload. Every value
is fixed by the server, so the SNARK verifier only has to match the vector exactly (popprover verify <vk> <proof>
<expected.json>); the index of the first mismatch maps to popzk's reason codes.

The SNARK verifier is the host build of app/prover (`popprover`, Spartan2 / Hyrax on T-256), run as a subprocess:
POP_ZK_VERIFIER (binary), POP_ZK_VK_DIR (<circuit>.vk, sha256-pinned), POP_ZK_WRAP (command prefix, e.g. the
machine lock). Proving keys for download: POP_ZK_KEYS (<circuit>.pk.zst). None of these files is in git.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np

from pop import poseidon7
from pop.popt2 import code_commit
from pop.verdict import Reject

P = poseidon7.P
TAG_HALF2 = 8
CIRCUITS = {48000: "oa2t_s48", 44100: "oa2t_s44"}
CIRCUIT_SR = {c: sr for sr, c in CIRCUITS.items()}
# sha256 of the verifying keys (spike verifier/pinned.json, setup of 2026-09-26). A new setup = new pins here.
VK_PINS = {"oa2t_s48": "488e44c9f5abd7557fca11c72dee976bf6e9617ecac3d097430adf1019625a3d",
           "oa2t_s44": "7c5cb18c54223cddb9a8fcc00c22e9fdb81a8a10de3d950d9534a81b3b89e4e0"}
KEY_FILE = re.compile(r"^(oa2t_s48|oa2t_s44)\.pk\.zst$")
MAX_PROOF_BYTES = 4 << 20
SALT_MAX = 1 << 248


def n_public(L: int) -> int:
    return 1 + 6 + 4 * L + 4


def parse_salt(v) -> int:
    """Decimal or 0x-hex, 0 <= salt < 2^248 (31 random bytes, like the holder secret)."""
    try:
        if isinstance(v, int) and not isinstance(v, bool):
            s = v
        elif isinstance(v, str) and v.strip().lower().startswith("0x"):
            s = int(v.strip(), 16)
        elif isinstance(v, str) and v.strip().isdigit():
            s = int(v.strip())
        else:
            raise ValueError
    except ValueError:
        raise ValueError("salt must be a decimal or 0x-hex integer") from None
    if not 0 <= s < SALT_MAX:
        raise ValueError("salt must be < 2^248")
    return s


def half_commit(t: dict, salt: int) -> int:
    """t = decoded POPT v2 (pop.codec.decode_transcript)."""
    n = t["nonce"]
    return poseidon7.sponge16(TAG_HALF2, [int.from_bytes(n[:16], "big"), int.from_bytes(n[16:], "big"), t["attempt"],
                                          1 if t["role"] == "B" else 0, t["sample_rate"], t["half"] % P, salt,
                                          int.from_bytes(t["pk_self"][1:33], "big"),
                                          int.from_bytes(t["pk_partner"][1:33], "big")])


def public_vector(t: dict, own_code: tuple[bytes, bytes], partner_code: tuple[bytes, bytes], issuer_pub65: bytes,
                  valid_at: int, salt: int) -> list[str]:
    """What a proof for this signed transcript must expose, as decimal strings (popprover's public.json)."""
    cc = code_commit(own_code, partner_code)
    n = t["nonce"]
    vals = [half_commit(t, salt), int.from_bytes(n[:16], "big"), int.from_bytes(n[16:], "big"), t["attempt"],
            1 if t["role"] == "B" else 0, int.from_bytes(cc[:16], "big"), int.from_bytes(cc[16:], "big")]
    for c in (*own_code, *partner_code):
        vals += np.frombuffer(c, dtype=np.int8).astype(int).tolist()
    vals += [int.from_bytes(issuer_pub65[1:33], "big"), int.from_bytes(issuer_pub65[33:65], "big"),
             t["sample_rate"], valid_at]
    return [str(v % P) for v in vals]


def reason_at(i: int, n: int) -> tuple[str, str]:
    """First mismatching public index -> (reason, what), popzk.verify_phone's codes."""
    L = (n - 11) // 4
    if i == 0:
        return "transcript_mismatch", "halfCommit (half, keys or salt)"
    if i in (1, 2):
        return "transcript_mismatch", "session_nonce"
    if i == 3:
        return "transcript_mismatch", "attempt"
    if i == 4:
        return "transcript_mismatch", "role"
    if i < 7 + 4 * L:
        return "transcript_mismatch", "code_commit / templates"
    if i < 9 + 4 * L:
        return "issuer_unknown", "issuer key is not this server's issuer"
    if i == 9 + 4 * L:
        return "transcript_mismatch", "sample_rate"
    return "transcript_mismatch", "validAt"


def compare(got: list[str], want: list[str], who: str = "") -> None:
    if len(got) != len(want):
        raise Reject("proof_invalid", f"{who}{len(got)} public values, want {len(want)}")
    i = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), None)
    if i is not None:
        r, what = reason_at(i, len(want))
        raise Reject(r, f"{who}public[{i}] {what} != derived")


class Unavailable(Exception):
    """The verifier can't run (binary / vk missing, timeout): a server problem, not the proof's."""


_sha_cache: dict[tuple, str] = {}


def file_sha256(p: Path) -> str:
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime_ns)
    if key not in _sha_cache:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""):
                h.update(b)
        _sha_cache[key] = h.hexdigest()
    return _sha_cache[key]


class Verifier:
    """popprover verify <vk> <proof> <expected.json>: SNARK verify, then exact public vector match."""
    _one = threading.Lock()   # one ~0.5 GB vk in memory at a time

    def __init__(self, binary: str | None, vk_dir: str | None, wrap: str | None = None,
                 pins: dict | None = None, timeout_s: float = 300):
        self.binary = Path(binary) if binary else None
        self.vk_dir = Path(vk_dir) if vk_dir else None
        self.wrap = shlex.split(wrap) if wrap else []
        self.pins, self.timeout_s = dict(pins or VK_PINS), timeout_s

    def vk(self, circuit: str) -> Path | None:
        return self.vk_dir / f"{circuit}.vk" if self.vk_dir else None

    def available(self, circuit: str) -> bool:
        vk = self.vk(circuit)
        return bool(self.binary and os.access(self.binary, os.X_OK) and vk and vk.is_file())

    def verify(self, circuit: str, proof: bytes, expected: list[str]) -> None:
        if circuit not in self.pins:
            raise Reject("circuit_unknown", f"{circuit} is not a pinned circuit")
        if not self.available(circuit):
            raise Unavailable(f"verifier or {circuit}.vk not configured")
        with self._one:
            if file_sha256(self.vk(circuit)) != self.pins[circuit]:
                raise Reject("circuit_unknown", f"{circuit}: verifying key does not match the pinned id")
            with tempfile.TemporaryDirectory(prefix="popzk-") as d:
                pf, ef = Path(d) / "p.proof", Path(d) / "expected.json"
                pf.write_bytes(proof)
                ef.write_text(json.dumps({"public": expected}))
                try:
                    r = subprocess.run([*self.wrap, str(self.binary), "verify", str(self.vk(circuit)), str(pf), str(ef)],
                                       capture_output=True, text=True, timeout=self.timeout_s)
                except (OSError, subprocess.TimeoutExpired) as e:
                    raise Unavailable(f"verifier: {e}") from None
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT")), None)
        if line is None:
            raise Unavailable(f"verifier rc={r.returncode}: {(r.stdout + r.stderr)[-200:]}")
        if " ACCEPT" in line and r.returncode == 0:
            return
        m = re.search(r"public\[(\d+)\] mismatch", line)
        if m:
            reason, what = reason_at(int(m.group(1)), len(expected))
            raise Reject(reason, f"public[{m.group(1)}] {what} != derived")
        raise Reject("proof_invalid", line[:200])


def key_manifest(keys_dir: str | None) -> list[dict]:
    """The proving keys on disk, for GET /v1/zk/keys. sha256 is of the exact bytes served."""
    out = []
    d = Path(keys_dir) if keys_dir else None
    for sr, c in sorted(CIRCUITS.items()):
        p = d / f"{c}.pk.zst" if d else None
        if p is not None and p.is_file():
            out.append({"circuit": c, "sample_rate": sr, "file": p.name, "url": f"/v1/zk/keys/{p.name}",
                        "size": p.stat().st_size, "sha256": file_sha256(p), "vk_sha256": VK_PINS[c]})
    return out
