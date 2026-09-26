#!/usr/bin/env python3
"""ENS bridge: PoP server results -> MeetResolver txs (Ethereum Sepolia). Stdlib + foundry `cast`.

  bridge.py status
  bridge.py once [--backfill]
  bridge.py run  [--backfill]                 poll every pollSeconds (default 3)
  bridge.py record <labelA> <labelB> [sessionId]
  bridge.py zk-verify <meetingId> <proof> <public_inputs>

Reads <dataDir>/sessions/<sid>/result.json written by server/pop/sessions.py. Never prints the key.
See bridge/README.md.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LABEL_RE = re.compile(r"^[a-z0-9-]{3,32}$")
SID_RE = re.compile(r"^[0-9a-f]{32}$")
TAG_HEX = "enconomy/meet/v1".encode().hex()
TX_BASE = "https://sepolia.etherscan.io/tx/"
ADDR_BASE = "https://sepolia.etherscan.io/address/"

DEFAULTS = {
    "rpc": "https://ethereum-sepolia-rpc.publicnode.com",
    "keyFile": "~/.enconomy/ens-sepolia.key",
    "deployments": str(REPO / "contracts/deployments/sepolia.json"),
    "zkDeployments": str(REPO / "contracts/deployments/zk-sepolia.json"),
    "dataDir": "~/dev/enconomy/server/data",
    "names": str(HERE / "names.json"),
    "state": str(HERE / "state.json"),
    "log": str(HERE / "log.jsonl"),
    "pollSeconds": 3,
    "phoneVerifier": None,     # overridden by zkDeployments.phoneVerifier when that file exists
    "verifyLog": None,         # contracts/zk/src/VerifyLog.sol: verifyAndLog(verifier, proof, publicInputs) -> Verified event
}

ERRORS = {}  # selector -> name, filled lazily


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ config / files

def load_json(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        return default


def save_json(p: Path, obj) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True))
    tmp.replace(p)


class Cfg:
    def __init__(self):
        path = Path(os.environ.get("BRIDGE_CONFIG", HERE / "config.json"))
        c = {**DEFAULTS, **(load_json(path, {}) or {})}
        env = {"rpc": "ETH_RPC", "keyFile": "ENS_KEY_FILE", "dataDir": "POP_DATA_DIR", "state": "BRIDGE_STATE",
               "log": "BRIDGE_LOG", "names": "BRIDGE_NAMES", "deployments": "ENS_OUT", "zkDeployments": "ZK_OUT"}
        for k, e in env.items():
            if os.environ.get(e):
                c[k] = os.environ[e]
        for k in ("keyFile", "deployments", "zkDeployments", "dataDir", "names", "state", "log"):
            c[k] = Path(os.path.expanduser(str(c[k])))
        self.c = c
        dep = load_json(c["deployments"])
        if not dep:
            die(f"no {c['deployments']} (ENS bootstrap not done?)")
        self.resolver = dep["meetResolver"]
        self.attester = dep["attester"]
        self.parent = dep["parent"]
        self.zkdep = load_json(c["zkDeployments"], {}) or {}
        self.phone_verifier = self.zkdep.get("phoneVerifier") or c["phoneVerifier"]
        self.verify_log = self.zkdep.get("verifyLog") or c["verifyLog"]

    def __getitem__(self, k):
        return self.c[k]


# ------------------------------------------------------------------ chain (cast)

class Chain:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg
        self.rpc = cfg["rpc"]
        self._pk = None
        self.me = None
        self.fork = None

    def cast(self, *args, check=True) -> str:
        p = subprocess.run(["cast", *args], capture_output=True, text=True)
        if check and p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout).strip().splitlines()[-1] if (p.stderr or p.stdout) else "cast failed")
        return p.stdout.strip()

    def call(self, to: str, sig: str, *args, frm: str | None = None) -> str:
        extra = ["--from", frm] if frm else []
        return self.cast("call", "--rpc-url", self.rpc, *extra, to, sig, *args)

    def is_fork(self) -> bool:
        if self.fork is None:
            self.fork = "anvil" in self.cast("client", "--rpc-url", self.rpc, check=False).lower()
        return self.fork

    def load_key(self) -> None:
        if self._pk:
            return
        kf = self.cfg["keyFile"]
        if not os.access(kf, os.R_OK):
            die(f"key file {kf} not readable")
        pk = "".join(kf.read_text().split())
        self._pk = pk if pk.startswith("0x") else "0x" + pk
        self.me = self.cast("wallet", "address", "--private-key", self._pk)

    def tx_link(self, h: str) -> str:
        return (TX_BASE + h) + (" (fork)" if self.is_fork() else "")

    def revert_name(self, msg: str) -> str:
        if not ERRORS:
            for s in ("NotRegistered(bytes32)", "SameName()", "DuplicateMeeting(bytes32)", "UnknownMeeting(bytes32)",
                      "Unauthorized()", "UnsupportedResolverProfile(bytes4)"):
                ERRORS[self.cast("sig", s)] = s.split("(")[0]
        m = re.search(r"0x[0-9a-fA-F]{8}", msg.split("data:")[-1]) if "data" in msg else None
        for sel, name in ERRORS.items():
            if sel in msg or (m and m.group(0).lower() == sel):
                return name
        return msg[:200]

    def wait_others(self) -> None:
        """The deploy / zk agents share this key. Don't race them: wait while their cast/ens.sh runs."""
        if self.is_fork():
            return
        for i in range(40):
            p = subprocess.run(["pgrep", "-fl", r"ens\.sh|cast send|forge (create|script)"], capture_output=True, text=True)
            others = [l for l in p.stdout.splitlines() if l.strip()]
            if not others:
                return
            if i == 0:
                print(f"· waiting for other tx senders: {others[0][:100]}", file=sys.stderr)
            time.sleep(3)
        print("· other senders still running; sending anyway (pending nonce)", file=sys.stderr)

    def send(self, to: str, sig: str, *args) -> dict:
        """cast send with the pending nonce; retries nonce races. Returns the receipt json."""
        self.load_key()
        last = ""
        for attempt in range(5):
            self.wait_others()
            nonce = self.cast("nonce", "--block", "pending", "--rpc-url", self.rpc, self.me)
            p = subprocess.run(["cast", "send", "--rpc-url", self.rpc, "--private-key", self._pk, "--json",
                                "--nonce", nonce, to, sig, *args], capture_output=True, text=True)
            if p.returncode == 0:
                rc = json.loads(p.stdout)
                if rc.get("status") not in ("0x1", 1, "1"):
                    raise RuntimeError(f"tx reverted {rc.get('transactionHash')}")
                return rc
            last = (p.stderr or p.stdout).strip()
            if re.search(r"nonce|underpriced|already known|replacement", last, re.I):
                time.sleep(2 + attempt * 2)
                continue
            break
        raise RuntimeError(last.splitlines()[-1] if last else "send failed")

    # -- MeetResolver reads
    def counts(self, label: str) -> tuple[bool, int, int, int]:
        out = self.call(self.cfg.resolver, "countsOf(bytes32)(bool,uint32,uint32,uint32)", keccak_str(self, label))
        v = out.split()
        return v[0] == "true", int(v[1]), int(v[2]), int(v[3])

    def meeting(self, mid: str) -> dict:
        out = self.call(self.cfg.resolver, "meetingOf(bytes32)(uint256,uint256,bool,bool,bool)", mid).split("\n")
        vals = [l.split()[0] for l in out]
        return {"exists": vals[2] == "true", "zk": vals[3] == "true", "voided": vals[4] == "true"}


def keccak_str(ch: Chain, s: str) -> str:
    return ch.cast("keccak", s)


def keccak_hex(ch: Chain, hexdata: str) -> str:
    return ch.cast("keccak", "0x" + hexdata.removeprefix("0x"))


def meeting_id(ch: Chain, sid: str) -> str:
    return keccak_hex(ch, TAG_HEX + sid)


def evidence(ch: Chain, sha_a: str, sha_b: str) -> str:
    for s in (sha_a, sha_b):
        if not re.fullmatch(r"[0-9a-f]{64}", s or ""):
            raise ValueError("transcript sha256 not 64 hex")
    return keccak_hex(ch, sha_a + sha_b)


# ------------------------------------------------------------------ log / state

class Out:
    def __init__(self, cfg: Cfg, ch: Chain):
        self.path, self.ch = cfg["log"], ch

    def __call__(self, action: str, msg: str, **kw) -> None:
        tx = kw.get("tx")
        line = f"{datetime.now().strftime('%H:%M:%S')} {action:<10} {msg}" + (f"  {self.ch.tx_link(tx)}" if tx else "")
        print(line, flush=True)
        # log.jsonl is meant for the web page: no session ids, device ids or display names (design §5.1 privacy)
        pub = kw.pop("pub", None) or msg
        kw.pop("session", None)
        rec = {"ts": now_iso(), "action": action, "msg": pub, "chain": "fork" if self.ch.is_fork() else "sepolia",
               **({"url": TX_BASE + tx} if tx else {}), **kw}
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")


class State:
    def __init__(self, path: Path):
        self.path = path
        self.d = load_json(path) or {}
        self.fresh = not self.d
        self.d.setdefault("sessions", {})

    def get(self, sid):
        return self.d["sessions"].get(sid)

    def put(self, sid, **kw):
        e = self.d["sessions"].setdefault(sid, {})
        e.update(kw, updated=now_iso())
        if e.get("status") != "ignored":
            self.d["last"] = sid
        self.save()

    def save(self):
        save_json(self.path, self.d)


# ------------------------------------------------------------------ names

def load_names(cfg: Cfg) -> dict:
    raw = load_json(cfg["names"], None)
    if raw is None:
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, str)}


def label_for(names: dict, dev: dict) -> str | None:
    return names.get(dev.get("device_id") or "") or names.get(dev.get("display_name") or "")


# ------------------------------------------------------------------ bridge

class Bridge:
    def __init__(self):
        self.cfg = Cfg()
        self.ch = Chain(self.cfg)
        self.log = Out(self.cfg, self.ch)
        self.state = State(self.cfg["state"])
        self.mtimes: dict[str, float] = {}
        self.reg_cache: dict[str, tuple[float, bool]] = {}

    @property
    def sessions_dir(self) -> Path:
        d = self.cfg["dataDir"]
        return d / "sessions" if (d / "sessions").is_dir() else d

    def results(self):
        d = self.sessions_dir
        if not d.is_dir():
            return
        for p in sorted(d.glob("*/result.json"), key=lambda p: p.stat().st_mtime):
            yield p

    def registered(self, label: str) -> bool:
        hit = self.reg_cache.get(label)
        if hit and time.time() - hit[0] < 30 and hit[1]:
            return True
        ok = self.ch.counts(label)[0]
        self.reg_cache[label] = (time.time(), ok)
        return ok

    # -- one pass
    def once(self, backfill: bool = False) -> None:
        if self.state.fresh and not backfill:
            n = 0
            for p in self.results():
                sid = p.parent.name
                self.state.d["sessions"].setdefault(sid, {"status": "preexisting", "updated": now_iso()})
                n += 1
            self.state.fresh = False
            self.state.d["baseline"] = now_iso()
            self.state.save()
            if n:
                self.log("baseline", f"{n} existing sessions marked preexisting (use --backfill to record them)")
        self.state.fresh = False
        names = load_names(self.cfg)
        for p in self.results():
            m = p.stat().st_mtime
            if self.mtimes.get(str(p)) == m:
                continue
            try:
                r = json.loads(p.read_text())
            except (ValueError, OSError):
                continue  # mid-write; retry next pass
            try:
                self.handle(r, names)
                self.mtimes[str(p)] = m
            except Exception as e:  # noqa: BLE001 - keep polling
                self.log("error", f"{p.parent.name[:8]} {e}", pub=f"error: {str(e)[:120]}")

    def handle(self, r: dict, names: dict) -> None:
        sid = r.get("session_id") or ""
        st = self.state.get(sid) or {}
        if st.get("status") == "preexisting":
            return
        if r.get("verdict") != "NEAR":
            if not st:
                self.state.put(sid, status="ignored", reason=f"verdict {r.get('verdict')}")
            return
        if not SID_RE.fullmatch(sid):
            self.state.put(sid, status="skipped", reason="bad session id")
            return
        if st.get("status") not in ("recorded", "duplicate"):
            self.record_session(r, names)
            st = self.state.get(sid) or {}
        if st.get("status") in ("recorded", "duplicate") and not st.get("zk_done"):
            zk = r.get("zk") or {}
            if zk.get("status") == "verified":
                self.zk_session(r, st)

    def skip(self, sid: str, reason: str, quiet_same=True) -> None:
        prev = self.state.get(sid) or {}
        if quiet_same and prev.get("status") == "skipped" and prev.get("reason") == reason:
            return
        self.state.put(sid, status="skipped", reason=reason)
        self.log("skip", f"{sid[:8]} {reason}", session=sid, pub="skip: " + reason.split(" B=")[0].split(" A=")[0])

    def record_session(self, r: dict, names: dict) -> None:
        sid = r["session_id"]
        dev = r.get("devices") or {}
        la, lb = label_for(names, dev.get("A") or {}), label_for(names, dev.get("B") or {})
        if not la or not lb:
            miss = [f"{k}={(dev.get(k) or {}).get('display_name')}/{(dev.get(k) or {}).get('device_id', '')[:8]}"
                    for k, l in (("A", la), ("B", lb)) if not l]
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
        if not isinstance(r.get("t0_ms"), int):
            return self.skip(sid, "no t0_ms")
        tb = r["t0_ms"] // 3_600_000
        self.do_record(la, lb, sid, tb, ev)

    def do_record(self, la: str, lb: str, sid: str, tb: int, ev: str) -> str | None:
        mid = meeting_id(self.ch, sid)
        if self.ch.meeting(mid)["exists"]:
            self.state.put(sid, status="duplicate", meetingId=mid, labels=[la, lb])
            self.log("record", f"{la} x {lb} already onchain (DuplicateMeeting) {mid[:10]}", session=sid, meetingId=mid)
            return mid
        self.ch.load_key()
        lha, lhb = keccak_str(self.ch, la), keccak_str(self.ch, lb)
        sig = "record(bytes32,bytes32,bytes32,uint32,bytes32)"
        try:
            first = self.ch.call(self.cfg.resolver, sig + "(bool)", mid, lha, lhb, str(tb), ev, frm=self.ch.me)
        except RuntimeError as e:
            name = self.ch.revert_name(str(e))
            if name == "DuplicateMeeting":
                self.state.put(sid, status="duplicate", meetingId=mid, labels=[la, lb])
                return mid
            self.skip(sid, f"record would revert: {name}")
            return None
        try:
            rc = self.ch.send(self.cfg.resolver, sig, mid, lha, lhb, str(tb), ev)
        except RuntimeError as e:
            name = self.ch.revert_name(str(e))
            if name == "DuplicateMeeting":
                self.state.put(sid, status="duplicate", meetingId=mid, labels=[la, lb])
                return mid
            raise
        tx = rc["transactionHash"]
        self.state.put(sid, status="recorded", meetingId=mid, labels=[la, lb], tx=tx, firstTime=first == "true",
                       timeBucket=tb, gas=int(rc.get("gasUsed", "0x0"), 16))
        self.log("record", f"{la} x {lb} meeting {mid[:10]} first={first}", tx=tx, session=sid, meetingId=mid,
                 labels=[la, lb], firstTime=first == "true")
        return mid

    # -- zk
    def find_proof(self, sid: str, role: str, attempt) -> tuple[Path | None, Path | None]:
        d = self.sessions_dir / sid
        proof = d / f"proof_{role}_{attempt}.bin"
        for name in (f"public_inputs_{role}_{attempt}.bin", f"public_inputs_{role}_{attempt}", f"public_inputs_{role}"):
            if (d / name).is_file():
                return (proof if proof.is_file() else None), d / name
        return (proof if proof.is_file() else None), None

    def zk_session(self, r: dict, st: dict) -> None:
        sid, mid = r["session_id"], st["meetingId"]
        vtx = dict(st.get("verifyTx") or {})
        m = self.ch.meeting(mid)
        if m["zk"] or m["voided"]:
            self.log("zk", f"{mid[:10]} already {'zk' if m['zk'] else 'void'} onchain", session=sid, meetingId=mid)
            self.state.put(sid, zk_done=True)
            return
        if self.cfg.phone_verifier:
            for role in ("A", "B"):
                if role in vtx:
                    continue
                ent = (r.get("zk") or {}).get(role) or {}
                pf, pi = self.find_proof(sid, role, ent.get("attempt", r.get("attempt", 0)))
                if not (pf and pi):
                    self.log("zk", f"{sid[:8]} {role}: no proof+public_inputs file, onchain verify skipped", session=sid,
                         pub=f"{mid[:10]} {role}: no proof file, onchain verify skipped", meetingId=mid)
                    vtx[role] = None
                    continue
                vtx[role] = self.verify_onchain(mid, pf, pi, session=sid, role=role)
        self.state.put(sid, verifyTx=vtx)
        tx = self.mark_zk(mid, session=sid)
        self.state.put(sid, zk_done=True, zkTx=tx)

    def verify_onchain(self, mid: str, proof: Path, pubs: Path, **kw) -> str | None:
        pb = proof.read_bytes()
        raw = pubs.read_bytes()
        if len(raw) % 32:
            raise ValueError(f"{pubs} is {len(raw)} bytes, not a multiple of 32")
        arr = "[" + ",".join("0x" + raw[i:i + 32].hex() for i in range(0, len(raw), 32)) + "]"
        ph = "0x" + pb.hex()
        try:
            ok = self.ch.call(self.cfg.phone_verifier, "verify(bytes,bytes32[])(bool)", ph, arr)
        except RuntimeError as e:
            ok = "revert " + str(e).split("data:")[-1].strip()[:40]
        if ok != "true":
            self.log("zk-verify", f"{mid[:10]} verifier returned {ok}; not sending", meetingId=mid, **kw)
            return None
        if self.cfg.verify_log:
            rc = self.ch.send(self.cfg.verify_log, "verifyAndLog(address,bytes,bytes32[])", self.cfg.phone_verifier, ph, arr)
            where = "VerifyLog"
        else:
            rc = self.ch.send(self.cfg.phone_verifier, "verify(bytes,bytes32[])", ph, arr)
            where = "phoneVerifier"
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
        rc = self.ch.send(self.cfg.resolver, "markZkVerified(bytes32)", mid)
        tx = rc["transactionHash"]
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
        except SystemExit:
            print(f"key          (unreadable)  attester {att}")
        print(f"phoneVerifier {cfg.phone_verifier or '-'}   verifyLog {cfg.verify_log or '-'}")
        print(f"data dir     {self.sessions_dir}  ({sum(1 for _ in self.results())} results)")
        names = load_names(cfg)
        print(f"names        {cfg['names']}  ({len(names)} entries)")
        for label in sorted(set(names.values())):
            keys = [k[:12] for k, v in names.items() if v == label]
            try:
                reg, met, mtg, zk = ch.counts(label) if LABEL_RE.fullmatch(label) else (False, 0, 0, 0)
                print(f"  {label:<14} {'registered' if reg else 'NOT REGISTERED':<15} met {met} meetings {mtg} zk {zk}  <- {', '.join(keys)}")
            except RuntimeError as e:
                print(f"  {label:<14} read error {e}")
        ss = self.state.d["sessions"]
        by = {}
        for e in ss.values():
            by[e.get("status")] = by.get(e.get("status"), 0) + 1
        print(f"state        {cfg['state']}  {dict(sorted(by.items())) or 'empty'}")
        last = self.state.d.get("last")
        if last:
            e = ss[last]
            print(f"last         {last[:8]} {e.get('status')} {e.get('labels', '')} {e.get('reason', '') or ''}"
                  f"{('  ' + ch.tx_link(e['tx'])) if e.get('tx') else ''}")


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.split("\n\n")[1] if __doc__ else "")
        return
    if not shutil.which("cast"):
        die("foundry `cast` not on PATH")
    cmd, rest = argv[0], argv[1:]
    backfill = "--backfill" in rest
    rest = [a for a in rest if a != "--backfill"]
    b = Bridge()
    if cmd == "status":
        b.status()
    elif cmd == "once":
        b.status()
        b.once(backfill)
    elif cmd == "run":
        b.status()
        print(f"polling every {b.cfg['pollSeconds']} s; ctrl-c to stop", flush=True)
        while True:
            b.once(backfill)
            backfill = False
            time.sleep(float(b.cfg["pollSeconds"]))
    elif cmd == "record":
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
        res = load_json(b.sessions_dir / sid / "result.json")
        if res and res.get("transcripts"):
            ev = evidence(b.ch, res["transcripts"]["A"]["sha256"], res["transcripts"]["B"]["sha256"])
            tb = res["t0_ms"] // 3_600_000
        else:  # rehearsal: no transcripts, random evidence (like ens.sh record)
            ev = keccak_hex(b.ch, secrets.token_hex(64))
            tb = int(time.time()) // 3600
        mid = b.do_record(la, lb, sid, tb, ev)
        if not mid:
            die("not recorded")
        print(f"meetingId {mid}  session {sid}")
    elif cmd == "zk-verify":
        if len(rest) != 3:
            die("zk-verify <meetingId> <proof> <public_inputs>")
        mid = rest[0]
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", mid):
            die("meetingId must be 0x + 64 hex")
        if b.cfg.phone_verifier:
            if not b.verify_onchain(mid, Path(rest[1]).expanduser(), Path(rest[2]).expanduser(), manual=True):
                die("onchain verify failed; not marking zk")
        else:
            b.log("zk-verify", "no phoneVerifier configured; skipping onchain verify", meetingId=mid)
        b.mark_zk(mid, manual=True)
    else:
        die(f"unknown command {cmd}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        pass
