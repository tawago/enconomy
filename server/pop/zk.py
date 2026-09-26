"""Option A proofs on Noir + Barretenberg UltraHonk (BN254): public vector, `bb verify`, served artifacts, delegated
proving. Contract with the app: zkmobile/APP_SERVER_CONTRACT.md.

Circuit `oaN_s48` = research/worldid/prototypes/optA-noir/noir/phone (nargo 1.0.0-beta.22, bb 5.0.0-nightly.20260522,
`-t evm`: keccak transcript, ZK). 48 kHz only; 44.1 kHz has no compiled circuit, so it is not provable.

  public (ABI order, return value last, 12 x 32 B big-endian in bb's public_inputs file):
    nonce_hi, nonce_lo, attempt, role_b, code_commit, issuerX hi128, issuerX lo128, issuerY hi128, issuerY lo128,
    sr, valid_at, halfCommit
  halfCommit = Poseidon2 hash_n(8, [nonce_hi, nonce_lo, attempt, role_b, sr, half mod r, salt,
                                    X_self hi, X_self lo, X_partner hi, X_partner lo])

The server derives all 12 itself (signed transcript, its own codes -> code_commit, its issuer key, valid_at, the
uploaded salt). An uploaded public_inputs file is only compared against that, to name the first mismatch; bb always
verifies against the server's own vector.

Binaries (none in git): POP_ZK_VERIFIER = bb (default ~/.enconomy/zk/pinned/bin/bb), POP_ZK_PROVER = zkprove host
build (zkmobile/android/zkprove, `zkprove full`: noir ACVM witness + bbapi prove, same bytes as `bb prove -t evm`;
default ~/.enconomy/zk/android/target/release/zkprove). Artifacts: POP_ZK_DIR/<served name> if present, else the
default source path below; each is sha256-pinned and never served or used when it doesn't match.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from pop import poseidon2 as p2
from pop.popt2 import code_commit_int
from pop.verdict import Reject

R = p2.R
CIRCUIT = "oaN_s48"
CIRCUITS = {48000: CIRCUIT}
CIRCUIT_SR = {c: sr for sr, c in CIRCUITS.items()}
N_PUBLIC = 12
VK_PINS = {CIRCUIT: "769ac93112de4ec2f970d33233108d19124612b9b2ae54b8b531a23ecaa23f06"}
_HOME = Path.home()
# served name -> (size, sha256, default source)
ARTIFACTS = {
    f"{CIRCUIT}.json": (14620501, "5499f99eed7aecfd6615ab470cfed7a3345e28954385005d8080b810aaf04f3a",
                        _HOME / ".enconomy/zk/optA/noir/phone/target/phone.json"),
    "bn254_g1_2p20.dat": (67108864, "5d0ff516149e0c6644ab16567b914c9d02bf41f872c1129af8436b41d4d82c62",
                          _HOME / ".bb-crs/bn254_g1.dat"),
    f"{CIRCUIT}.vk": (1888, VK_PINS[CIRCUIT], _HOME / ".enconomy/zk/pinned/vk/vk"),
}
KEY_FILE = re.compile(r"^(oaN_s48\.json|oaN_s48\.vk|bn254_g1_2p20\.dat)$")
DEFAULT_BB = _HOME / ".enconomy/zk/pinned/bin/bb"
DEFAULT_PROVER = _HOME / ".enconomy/zk/android/target/release/zkprove"
MAX_PROOF_BYTES = 64 << 10
SALT_MAX = 1 << 248
# phone ABI parameter names (phone.json), for the delegated input map
PUBLIC_PARAMS = ("nonce_hi", "nonce_lo", "attempt", "role_b", "code_commit", "issuer", "sr", "valid_at")
PRIVATE_PARAMS = ("t", "sig", "exp", "hold", "csig", "salt", "c_is", "c_qs", "c_ip", "c_qp", "xs", "chs", "leaf_s",
                  "xp", "chp", "leaf_p", "ci", "cq", "u")


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


def _limbs(b32: bytes) -> list[int]:
    return [int.from_bytes(b32[:16], "big"), int.from_bytes(b32[16:], "big")]


def half_commit(t: dict, salt: int) -> int:
    """t = decoded POPT v2 (pop.codec.decode_transcript)."""
    n = t["nonce"]
    return p2.half_commit(int.from_bytes(n[:16], "big"), int.from_bytes(n[16:], "big"), t["attempt"],
                          t["role"] == "B", t["sample_rate"], t["half"], salt, t["pk_self"][1:33],
                          t["pk_partner"][1:33])


def public_vector(t: dict, own_code: tuple[bytes, bytes], partner_code: tuple[bytes, bytes], issuer_pub65: bytes,
                  valid_at: int, salt: int) -> list[int]:
    """The 12 public inputs a proof for this signed transcript must carry."""
    n = t["nonce"]
    return [*_limbs(n), t["attempt"], 1 if t["role"] == "B" else 0, code_commit_int(own_code, partner_code),
            *_limbs(issuer_pub65[1:33]), *_limbs(issuer_pub65[33:65]), t["sample_rate"], valid_at,
            half_commit(t, salt)]


def to_file(vals: list[int]) -> bytes:
    return b"".join((v % R).to_bytes(32, "big") for v in vals)


def from_file(raw: bytes) -> list[int]:
    if len(raw) != 32 * N_PUBLIC:
        raise Reject("proof_invalid", f"public_inputs must be {32 * N_PUBLIC} bytes, got {len(raw)}")
    return [int.from_bytes(raw[i:i + 32], "big") for i in range(0, len(raw), 32)]


def hexes(vals: list[int]) -> list[str]:
    return ["0x%064x" % (v % R) for v in vals]


def reason_at(i: int) -> tuple[str, str]:
    """First mismatching public index -> (reason, what)."""
    if i in (0, 1):
        return "transcript_mismatch", "session_nonce"
    if i == 2:
        return "transcript_mismatch", "attempt"
    if i == 3:
        return "transcript_mismatch", "role"
    if i == 4:
        return "transcript_mismatch", "code_commit (not the codes this server sent)"
    if i < 9:
        return "issuer_unknown", "issuer key is not this server's issuer"
    if i == 9:
        return "transcript_mismatch", "sample_rate"
    if i == 10:
        return "transcript_mismatch", "validAt"
    return "transcript_mismatch", "halfCommit (half, keys or salt)"


def compare(got: list[int], want: list[int], who: str = "") -> None:
    if len(got) != len(want):
        raise Reject("proof_invalid", f"{who}{len(got)} public values, want {len(want)}")
    i = next((i for i, (a, b) in enumerate(zip(got, want)) if a % R != b % R), None)
    if i is not None:
        r, what = reason_at(i)
        raise Reject(r, f"{who}public[{i}] {what} != derived")


class Unavailable(Exception):
    """The verifier / prover can't run (binary / artifact missing, timeout): a server problem, not the proof's."""


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


class Artifacts:
    """Pinned circuit files: POP_ZK_DIR/<name> first, else the default source."""

    def __init__(self, zk_dir: str | None = None, pins: dict | None = None):
        self.dir = Path(zk_dir).expanduser() if zk_dir else None
        self.pins = dict(pins or ARTIFACTS)

    def path(self, name: str) -> Path | None:
        if name not in self.pins:
            return None
        p = self.dir / name if self.dir else None
        if p is None or not p.is_file():
            p = Path(self.pins[name][2])
        return p if p.is_file() else None

    def ok(self, name: str) -> Path | None:
        """The file, only if its size + sha256 match the pin."""
        p = self.path(name)
        if p is None:
            return None
        size, sha, _ = self.pins[name]
        return p if p.stat().st_size == size and file_sha256(p) == sha else None

    def manifest(self) -> list[dict]:
        out = []
        for name, (size, sha, _) in self.pins.items():
            if self.ok(name) is not None:
                out.append({"circuit": CIRCUIT, "sample_rate": CIRCUIT_SR[CIRCUIT], "file": name,
                            "url": f"/v1/zk/keys/{name}", "size": size, "sha256": sha, "vk_sha256": VK_PINS[CIRCUIT]})
        return out


def _run(cmd: list[str], timeout_s: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unavailable(f"{Path(cmd[0]).name}: {e}") from None


class Verifier:
    """bb verify -t evm -k <pinned vk> -p proof -i <server-derived public inputs>."""

    def __init__(self, binary: str | None, artifacts: Artifacts, wrap: str | None = None,
                 pins: dict | None = None, timeout_s: float = 120):
        self.binary = Path(binary).expanduser() if binary else None
        self.art, self.wrap = artifacts, shlex.split(wrap) if wrap else []
        self.pins, self.timeout_s = dict(pins or VK_PINS), timeout_s

    def vk(self, circuit: str) -> Path | None:
        return self.art.path(f"{circuit}.vk")

    def available(self, circuit: str) -> bool:
        vk = self.vk(circuit)
        return bool(self.binary and os.access(self.binary, os.X_OK) and vk)

    def verify(self, circuit: str, proof: bytes, expected: list[int]) -> None:
        if circuit not in self.pins:
            raise Reject("circuit_unknown", f"{circuit} is not a pinned circuit")
        if not self.available(circuit):
            raise Unavailable(f"bb or {circuit}.vk not configured")
        vk = self.vk(circuit)
        if file_sha256(vk) != self.pins[circuit]:
            raise Reject("circuit_unknown", f"{circuit}: verifying key does not match the pinned id")
        with tempfile.TemporaryDirectory(prefix="popzk-") as d:
            pf, pi = Path(d) / "proof", Path(d) / "public_inputs"
            pf.write_bytes(proof)
            pi.write_bytes(to_file(expected))
            r = _run([*self.wrap, str(self.binary), "verify", "-t", "evm", "-k", str(vk), "-p", str(pf), "-i", str(pi)],
                     self.timeout_s)
        out = r.stdout + r.stderr
        if r.returncode == 0 and "verified successfully" in out:
            return
        raise Reject("proof_invalid", "bb verify: " + (out.strip().splitlines() or ["failed"])[-1][:200])


def _toml_val(v, depth: int = 0) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        if v < 0:
            raise ValueError("negative integer (Fields go as decimal strings mod r)")
        return str(v)
    if isinstance(v, str):
        if not re.fullmatch(r"[0-9]{1,78}|0x[0-9a-fA-F]{1,64}", v):
            raise ValueError("strings must be decimal or 0x-hex field elements")
        return f'"{v}"'
    if isinstance(v, list) and depth < 4:
        return "[" + ", ".join(_toml_val(x, depth + 1) for x in v) + "]"
    raise ValueError(f"unsupported value {type(v).__name__}")


def prover_toml(inputs: dict) -> str:
    """The app's Noir input map (contract: Field = decimal string, uN = number, bool, nested arrays) -> Prover.toml."""
    names = (*PUBLIC_PARAMS, *PRIVATE_PARAMS)
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be an object")
    if set(inputs) != set(names):
        missing, extra = sorted(set(names) - set(inputs)), sorted(set(inputs) - set(names))
        raise ValueError(f"inputs must be exactly the phone ABI parameters (missing {missing[:5]}, extra {extra[:5]})")
    return "".join(f"{k} = {_toml_val(inputs[k])}\n" for k in names)


def field_of(v) -> int:
    """An input-map scalar (number, decimal / hex string, bool) as an int."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return int(v, 16) if v.startswith("0x") else int(v)
    raise ValueError("not a scalar")


def inputs_public(inputs: dict) -> list[int]:
    """The first 11 public values as the input map states them (ABI order)."""
    iss = inputs["issuer"]
    if not isinstance(iss, list) or len(iss) != 4:
        raise ValueError("issuer must be 4 limbs")
    return [field_of(inputs["nonce_hi"]), field_of(inputs["nonce_lo"]), field_of(inputs["attempt"]),
            field_of(inputs["role_b"]), field_of(inputs["code_commit"]), *(field_of(x) for x in iss),
            field_of(inputs["sr"]), field_of(inputs["valid_at"])]


class Prover:
    """zkprove full <phone.json> <Prover.toml> <crs> <vk> <out>: one job at a time (~1.3 GB, ~10-20 s on an M2).
    The input map (private audio windows, templates, signatures) only lives in a 0700 temp dir during the run."""
    _one = threading.Lock()

    def __init__(self, binary: str | None, artifacts: Artifacts, wrap: str | None = None, timeout_s: float = 300):
        self.binary = Path(binary).expanduser() if binary else None
        self.art, self.wrap, self.timeout_s = artifacts, shlex.split(wrap) if wrap else [], timeout_s

    def files(self, circuit: str) -> tuple[Path, Path, Path] | None:
        f = (self.art.ok(f"{circuit}.json"), self.art.ok("bn254_g1_2p20.dat"), self.art.ok(f"{circuit}.vk"))
        return f if all(f) else None

    def available(self, circuit: str) -> bool:
        return bool(self.binary and os.access(self.binary, os.X_OK) and circuit in VK_PINS and self.files(circuit))

    def prove(self, circuit: str, toml: str) -> tuple[bytes, bytes]:
        """-> (proof, public_inputs). Reject("witness_failed") when the ACVM rejects the inputs."""
        if not self.available(circuit):
            raise Unavailable(f"prover or {circuit} artifacts not configured")
        art, crs, vk = self.files(circuit)
        with self._one:
            d = tempfile.mkdtemp(prefix="popzk-prove-")
            try:
                os.chmod(d, 0o700)
                inp, out = Path(d) / "Prover.toml", Path(d) / "out"
                inp.write_text(toml)
                r = _run([*self.wrap, str(self.binary), "full", str(art), str(inp), str(crs), str(vk), str(out)],
                         self.timeout_s)
                if r.returncode == 0 and (out / "proof").is_file():
                    return (out / "proof").read_bytes(), (out / "public_inputs").read_bytes()
            finally:
                shutil.rmtree(d, ignore_errors=True)
        err = (r.stderr + r.stdout).strip()
        m = re.search(r"(witness solve.*|acvm:.*|inputs:.*)", err)
        if m:
            raise Reject("witness_failed", m.group(1)[:200])
        raise Unavailable(f"zkprove rc={r.returncode}: {err[-200:]}")
