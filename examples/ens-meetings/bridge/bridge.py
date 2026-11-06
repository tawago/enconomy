#!/usr/bin/env python3
"""ENS bridge: presence records in this example's sqlite -> MeetResolver txs (Ethereum Sepolia). Needs foundry `cast`.

  bridge status
  bridge record <labelA> <labelB> [sessionId]
  bridge zk-verify <meetingId> <proof> <public_inputs>
  bridge import-names <old core sqlite> [ens.sqlite]
  bridge run                                  says how to start the backend, whose worker does this

The backend's worker thread calls Bridge.once after each claim or record. Names come from ens_names, work and
per-session status from presence_records. The only thing it asks the core for is the public ZK bundle. Never prints
the key. See bridge/README.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backend import import_names
from backend.chain import TX_BASE, Chain
from backend.core import ROLES, SID_RE
from backend.store import LABEL_RE, Store

HERE = Path(__file__).resolve().parent
TAG_HEX = "enconomy/meet/v1".encode().hex()
ADDR_BASE = "https://sepolia.etherscan.io/address/"
WORD_RE = re.compile(r"0x[0-9a-f]{64}")
DONE = ("recorded", "duplicate")
MAX_BUNDLE = 4 << 20   # three proofs of about 10 KB, as hex

DEFAULTS = {
    "rpc": "https://ethereum-sepolia-rpc.publicnode.com",
    "keyFile": "~/.enconomy/ens-sepolia.key",
    "deployments": str(HERE.parent / "contracts/deployments/sepolia.json"),
    "zkDeployments": str(HERE.parent / "contracts/deployments/zk-sepolia.json"),
    "db": str(HERE.parent / "data/ens.sqlite"),
    "log": str(HERE / "log.jsonl"),
    "coreUrl": "http://127.0.0.1:8000",
    "phoneVerifier": None,     # overridden by zkDeployments.phoneVerifier when that file exists
    "verifyLog": None,         # verifyAndLog(verifier, proof, publicInputs) -> Verified event
}
ENV = {"rpc": "ETH_RPC", "keyFile": "ENS_KEY_FILE", "deployments": "ENS_DEPLOYMENTS", "zkDeployments": "ENS_ZK_DEPLOYMENTS",
       "db": "ENS_DB", "log": "BRIDGE_LOG", "coreUrl": "ENS_CORE_URL"}


class ZkRefused(Exception):
    """The bundle doesn't match what the core signed. No verify tx and no mark; the record stays undone."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        return default


class Cfg:
    """DEFAULTS, then config.json, then the environment, then what the caller passes (None passes nothing)."""

    def __init__(self, **over):
        path = Path(os.environ.get("BRIDGE_CONFIG", HERE / "config.json"))
        c = {**DEFAULTS, **(load_json(path, {}) or {})}
        c.update({k: os.environ[e] for k, e in ENV.items() if os.environ.get(e)})
        c.update({k: v for k, v in over.items() if v is not None})
        for k in ("keyFile", "deployments", "zkDeployments", "db", "log"):
            c[k] = Path(os.path.expanduser(str(c[k])))
        c["coreUrl"] = str(c["coreUrl"]).rstrip("/")
        self.c = c
        dep = load_json(c["deployments"])
        if not dep:
            raise RuntimeError(f"no {c['deployments']}")
        self.resolver, self.registry, self.parent = dep["meetResolver"], dep["registry"], dep["parent"]
        zkdep = load_json(c["zkDeployments"], {}) or {}
        self.phone_verifier = zkdep.get("phoneVerifier") or c["phoneVerifier"]
        self.verify_log = zkdep.get("verifyLog") or c["verifyLog"]

    def __getitem__(self, k):
        return self.c[k]


def http_get_json(url: str, timeout: float = 20) -> tuple[int, dict | None]:
    """(status, json). A network error raises, and the record is tried again on a later pass."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as f:
            raw, status = f.read(MAX_BUNDLE + 1), f.status
    except urllib.error.HTTPError as e:
        return e.code, None
    if len(raw) > MAX_BUNDLE:
        raise RuntimeError(f"zk bundle over {MAX_BUNDLE} bytes")   # no url: errors reach log.jsonl, which has no session ids
    return status, json.loads(raw)


# ------------------------------------------------------------------ formulas (design §5.1). Deployed data: don't change

def meeting_id(ch, sid: str) -> str:
    return ch.keccak_hex(TAG_HEX + sid)


def evidence(ch, sha_a: str, sha_b: str) -> str:
    for s in (sha_a, sha_b):
        if not re.fullmatch(r"[0-9a-f]{64}", s or ""):
            raise ValueError("transcript sha256 not 64 hex")
    return ch.keccak_hex(sha_a + sha_b)


def time_bucket(t0_ms: int) -> int:
    return t0_ms // 3_600_000


def words(public_inputs: list[str]) -> bytes:
    """["0x" + 64 hex, ...] -> what verify_onchain takes: raw 32-byte words, the bb file format."""
    return b"".join(bytes.fromhex(w[2:]) for w in public_inputs)


# ------------------------------------------------------------------ log

class Out:
    def __init__(self, path: Path, ch):
        self.path, self.ch = path, ch

    def __call__(self, action: str, msg: str, **kw) -> None:
        tx = kw.get("tx")
        line = f"{datetime.now().strftime('%H:%M:%S')} {action:<10} {msg}" + (f"  {self.ch.tx_link(tx)}" if tx else "")
        print(line, flush=True)
        # log.jsonl is safe to publish: no session ids or device ids (design §5.1 privacy)
        pub = kw.pop("pub", None) or msg
        kw.pop("session", None)
        rec = {"ts": now_iso(), "action": action, "msg": pub, "chain": "fork" if self.ch.is_fork() else "sepolia",
               **({"url": TX_BASE + tx} if tx else {}), **kw}
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")


# ------------------------------------------------------------------ bridge

class Bridge:
    def __init__(self, store: Store, chain, cfg: Cfg, http_get=None):
        self.store, self.ch, self.cfg = store, chain, cfg
        self.http_get = http_get or http_get_json
        self.log = Out(cfg["log"], chain)
        self.reg_cache: dict[str, tuple[float, bool]] = {}

    def names(self) -> dict:
        """device_id -> label of the registered rows in ens_names."""
        return {r["device_id"]: r["label"] for r in self.store.names_with_status("registered")}

    def registered(self, label: str) -> bool:
        hit = self.reg_cache.get(label)
        if hit and time.time() - hit[0] < 30 and hit[1]:
            return True
        ok = self.ch.counts(label)[0]
        self.reg_cache[label] = (time.time(), ok)
        return ok

    # -- one pass
    def once(self, stop=lambda: False) -> None:
        names = self.names()
        for row in self.store.undone_records():
            if stop():
                return
            try:
                self.handle(row, names)
            except Exception as e:  # noqa: BLE001 - this record stays undone, the others still go
                self.store.set_session(row["session_id"], reason=str(e)[:200])
                self.log("error", f"{row['session_id'][:8]} {e}", pub=f"error: {str(e)[:120]}")

    def handle(self, row: dict, names: dict) -> None:
        sid, r = row["session_id"], json.loads(row["body"])
        if r.get("verdict") != "NEAR":
            self.store.set_session(sid, status="ignored", reason=f"verdict {r.get('verdict')}")
            return
        if row["status"] not in DONE:
            self.record_session(r, names)
            row = self.store.get_record(sid)
        if row["status"] in DONE and not row["zk_done"] and (r.get("zk") or {}).get("status") == "verified":
            self.zk_session(r, row)

    def skip(self, sid: str, reason: str) -> None:
        prev = self.store.get_record(sid)
        if prev and prev["status"] == "skipped" and prev["reason"] == reason:
            return
        self.store.set_session(sid, status="skipped", reason=reason)
        self.log("skip", f"{sid[:8]} {reason}", session=sid, pub="skip: " + reason.split(" B=")[0].split(" A=")[0])

    def record_session(self, r: dict, names: dict) -> None:
        sid, dev = r["session_id"], r.get("devices") or {}
        la, lb = (names.get((dev.get(k) or {}).get("device_id") or "") for k in ROLES)
        if not la or not lb:
            miss = [f"{k}={(dev.get(k) or {}).get('device_id', '')[:8]}" for k, l in (("A", la), ("B", lb)) if not l]
            return self.skip(sid, "unmapped device " + ", ".join(miss))
        if la == lb:
            return self.skip(sid, f"same label {la}")
        for l in (la, lb):
            if not LABEL_RE.fullmatch(l):
                return self.skip(sid, f"bad label {l!r}")
            if not self.registered(l):
                return self.skip(sid, f"{l}.{self.cfg.parent} not registered")
        tr = r.get("transcripts") or {}
        try:
            ev = evidence(self.ch, (tr.get("A") or {}).get("sha256"), (tr.get("B") or {}).get("sha256"))
        except ValueError as e:
            return self.skip(sid, str(e))
        if type(r.get("t0_ms")) is not int:
            return self.skip(sid, "no t0_ms")
        self.do_record(la, lb, sid, time_bucket(r["t0_ms"]), ev)

    def _duplicate(self, sid: str, mid: str, la: str, lb: str) -> str:
        self.store.set_session(sid, status="duplicate", reason=None, meeting_id=mid, labels=[la, lb])
        return mid

    def do_record(self, la: str, lb: str, sid: str, tb: int, ev: str) -> str | None:
        mid = meeting_id(self.ch, sid)
        if self.ch.meeting(mid)["exists"]:
            self._duplicate(sid, mid, la, lb)
            self.log("record", f"{la} x {lb} already onchain (DuplicateMeeting) {mid[:10]}", session=sid, meetingId=mid)
            return mid
        lha, lhb = self.ch.keccak_str(la), self.ch.keccak_str(lb)
        try:
            first = self.ch.record_would(mid, lha, lhb, tb, ev)
        except RuntimeError as e:
            name = self.ch.revert_name(str(e))
            if name == "DuplicateMeeting":
                return self._duplicate(sid, mid, la, lb)
            self.skip(sid, f"record would revert: {name}")
            return None
        try:
            rc = self.ch.record(mid, lha, lhb, tb, ev)
        except RuntimeError as e:
            if self.ch.revert_name(str(e)) == "DuplicateMeeting":
                return self._duplicate(sid, mid, la, lb)
            raise
        tx = rc["transactionHash"]
        self.store.set_session(sid, status="recorded", reason=None, meeting_id=mid, labels=[la, lb], tx=tx,
                               first_time=first == "true", time_bucket=tb, gas=int(rc.get("gasUsed", "0x0"), 16))
        self.log("record", f"{la} x {lb} meeting {mid[:10]} first={first}", tx=tx, session=sid, meetingId=mid,
                 labels=[la, lb], firstTime=first == "true")
        return mid

    # -- zk
    def fetch_proofs(self, r: dict) -> dict | None:
        """role -> (proof, public inputs) in bytes, or (None, None) if the core kept no proof file. None if the bundle
        isn't out yet: it's 404 until the pair proof verifies. The bundle is public and unsigned, so each proof must hash
        to what the core signed and its inputs must equal the signed ones. ZkRefused if any doesn't."""
        sid, signed = r["session_id"], r.get("zk") or {}
        status, b = self.http_get(f"{self.cfg['coreUrl']}/v1/session/{sid}/zk/bundle")
        if status == 404:
            return None
        if status != 200:
            raise RuntimeError(f"zk bundle: HTTP {status}")
        if not isinstance(b, dict) or b.get("session_id") != sid or not isinstance(b.get("proofs"), dict):
            raise ZkRefused("bundle is for another session")
        out = {}
        for role in ROLES:
            p, z = b["proofs"].get(role), signed.get(role)
            if not isinstance(p, dict) or not isinstance(z, dict):
                raise ZkRefused(f"{role}: no proof entry")
            if p.get("proof") is None:
                out[role] = (None, None)
                continue
            try:
                proof = bytes.fromhex(p["proof"].removeprefix("0x"))
            except (AttributeError, ValueError):
                raise ZkRefused(f"{role}: proof is not hex") from None
            if hashlib.sha256(proof).hexdigest() != z.get("proof_sha256"):
                raise ZkRefused(f"{role}: proof sha256 is not the signed one")
            pubs = z.get("public_inputs")
            if p.get("public_inputs") != pubs or not isinstance(pubs, list) \
                    or not all(isinstance(w, str) and WORD_RE.fullmatch(w) for w in pubs):
                raise ZkRefused(f"{role}: public inputs are not the signed ones")
            out[role] = (proof, words(pubs))
        return out

    def zk_session(self, r: dict, row: dict) -> None:
        sid, mid = r["session_id"], row["meeting_id"]
        vtx = json.loads(row["verify_tx"] or "{}")
        m = self.ch.meeting(mid)
        if m["zk"] or m["voided"]:
            self.log("zk", f"{mid[:10]} already {'zk' if m['zk'] else 'void'} onchain", session=sid, meetingId=mid)
            self.store.set_session(sid, zk_done=1)
            return
        if self.cfg.phone_verifier and any(role not in vtx for role in ROLES):
            try:
                proofs = self.fetch_proofs(r)
            except ZkRefused as e:
                reason = f"zk refused: {e}"
                if row["reason"] != reason:
                    self.store.set_session(sid, reason=reason)
                    self.log("zk", f"{mid[:10]} {reason}", session=sid, meetingId=mid)
                return
            if proofs is None:
                self.log("zk", f"{mid[:10]} zk bundle not out (no pair proof yet), onchain verify skipped", session=sid,
                         meetingId=mid)
                proofs = {}
            for role in ROLES:
                if role in vtx:
                    continue
                pf, pi = proofs.get(role, (None, None))
                if pf is None:
                    self.log("zk", f"{mid[:10]} {role}: no proof, onchain verify skipped", session=sid, meetingId=mid)
                    vtx[role] = None
                else:
                    vtx[role] = self.verify_onchain(mid, pf, pi, session=sid, role=role)
                self.store.set_session(sid, verify_tx=vtx)   # each one: a failure on B must not send A's 4 M gas again
        tx = self.mark_zk(mid, session=sid)
        self.store.set_session(sid, zk_done=1, zk_tx=tx, reason=None)

    def verify_onchain(self, mid: str, proof: bytes, pubs: bytes, **kw) -> str | None:
        if len(pubs) % 32:
            raise ValueError(f"public inputs are {len(pubs)} bytes, not a multiple of 32")
        arr = "[" + ",".join("0x" + pubs[i:i + 32].hex() for i in range(0, len(pubs), 32)) + "]"
        ph = "0x" + proof.hex()
        try:
            ok = self.ch.verify_call(self.cfg.phone_verifier, ph, arr)
        except RuntimeError as e:
            ok = "revert " + str(e).split("data:")[-1].strip()[:40]
        if ok != "true":
            self.log("zk-verify", f"{mid[:10]} verifier returned {ok}; not sending", meetingId=mid, **kw)
            return None
        rc = self.ch.verify_send(self.cfg.phone_verifier, self.cfg.verify_log, ph, arr)
        where = "VerifyLog" if self.cfg.verify_log else "phoneVerifier"
        tx = rc["transactionHash"]
        self.log("zk-verify", f"{mid[:10]} proof ok via {where} gas {int(rc.get('gasUsed', '0x0'), 16)}", tx=tx,
                 meetingId=mid, **kw)
        return tx

    def mark_zk(self, mid: str, **kw) -> str | None:
        m = self.ch.meeting(mid)
        if not m["exists"]:
            raise RuntimeError(f"meeting {mid[:10]} not onchain (UnknownMeeting)")
        if m["zk"] or m["voided"]:
            self.log("zk", f"{mid[:10]} already {'zk' if m['zk'] else 'void'}", meetingId=mid, **kw)
            return None
        tx = self.ch.mark_zk(mid)["transactionHash"]
        self.log("zk", f"{mid[:10]} markZkVerified", tx=tx, meetingId=mid, **kw)
        return tx

    # -- status
    def status(self) -> None:
        ch, cfg = self.ch, self.cfg
        chain_id = ch.cast("chain-id", "--rpc-url", ch.rpc)
        print(f"rpc          {ch.rpc}  chain {chain_id}{'  (anvil fork)' if ch.is_fork() else ''}")
        print(f"resolver     {cfg.resolver}  {ADDR_BASE + cfg.resolver}")
        att = ch.call(cfg.resolver, "attester()(address)")
        try:
            ch.load_key()
            bal = ch.cast("balance", "--ether", "--rpc-url", ch.rpc, ch.me)
            print(f"key          {ch.me}  {bal} ETH  attester {'OK' if att.lower() == ch.me.lower() else 'MISMATCH ' + att}")
        except RuntimeError:
            print(f"key          (unreadable)  attester {att}")
        print(f"phoneVerifier {cfg.phone_verifier or '-'}   verifyLog {cfg.verify_log or '-'}")
        names = self.names()
        print(f"names        {cfg['db']} ens_names registered  ({len(names)} entries)")
        for dev, label in sorted(names.items(), key=lambda kv: kv[1]):
            try:
                reg, met, mtg, zk = ch.counts(label) if LABEL_RE.fullmatch(label) else (False, 0, 0, 0)
                print(f"  {label:<14} {'registered' if reg else 'NOT REGISTERED':<15} met {met} meetings {mtg} zk {zk}  <- {dev[:12]}")
            except RuntimeError as e:
                print(f"  {label:<14} read error {e}")
        print(f"records      {self.store.session_counts() or 'empty'}  undone {len(self.store.undone_records())}")


def make_bridge() -> Bridge:
    cfg = Cfg()
    chain = Chain(cfg["rpc"], cfg["keyFile"], cfg.resolver, cfg.registry)
    return Bridge(Store(cfg["db"]), chain, cfg)


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def cmd_record(b: Bridge, rest: list[str]) -> None:
    if len(rest) not in (2, 3):
        die("record <labelA> <labelB> [sessionId]")
    la, lb = rest[0], rest[1]
    for l in (la, lb):
        if not LABEL_RE.fullmatch(l):
            die(f"bad label {l!r}")
    if la == lb:
        die("same label")
    sid = (rest[2] if len(rest) == 3 else secrets.token_hex(16)).lower().removeprefix("0x")
    if not SID_RE.fullmatch(sid):
        die("sessionId must be 32 hex")
    row = b.store.get_record(sid)
    body = json.loads(row["body"]) if row else {}
    tr = body.get("transcripts") or {}
    if "A" in tr and "B" in tr:
        ev, tb = evidence(b.ch, tr["A"]["sha256"], tr["B"]["sha256"]), time_bucket(body["t0_ms"])
    else:  # rehearsal: no record, random evidence (like ens.sh record)
        ev, tb = b.ch.keccak_hex(secrets.token_hex(64)), int(time.time()) // 3600
    mid = b.do_record(la, lb, sid, tb, ev)
    if not mid:
        die("not recorded")
    print(f"meetingId {mid}  session {sid}")


def cmd_zk_verify(b: Bridge, rest: list[str]) -> None:
    if len(rest) != 3:
        die("zk-verify <meetingId> <proof> <public_inputs>")
    mid = rest[0]
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", mid):
        die("meetingId must be 0x + 64 hex")
    if b.cfg.phone_verifier:
        proof, pubs = (Path(p).expanduser().read_bytes() for p in rest[1:])
        if not b.verify_onchain(mid, proof, pubs, manual=True):
            die("onchain verify failed; not marking zk")
    else:
        b.log("zk-verify", "no phoneVerifier configured; skipping onchain verify", meetingId=mid)
    b.mark_zk(mid, manual=True)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.split("\n\n")[1])
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "import-names":
        return import_names.main(rest)
    if cmd == "run":
        print("the backend's worker does this, woken by claims and records. Start it from the example root:\n"
              "  uv run --env-file .env uvicorn --factory backend.main:create_app --port 8100")
        return 0
    if cmd not in ("status", "record", "zk-verify"):
        die(f"unknown command {cmd}")
    if not shutil.which("cast"):
        die("foundry `cast` not on PATH")
    try:
        b = make_bridge()
        if cmd == "status":
            b.status()
        elif cmd == "record":
            cmd_record(b, rest)
        else:
            cmd_zk_verify(b, rest)
    except RuntimeError as e:
        die(str(e))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        pass
