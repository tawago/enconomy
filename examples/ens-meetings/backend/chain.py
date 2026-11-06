"""MeetResolver and registry over foundry `cast` (Ethereum Sepolia). Never prints the key.
One worker thread uses this, so the shared key has no nonce race inside this process; other senders still can."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TX_BASE = "https://sepolia.etherscan.io/tx/"
RECORD_SIG = "record(bytes32,bytes32,bytes32,uint32,bytes32)"
NAME_TTL = 90 * 86400   # same as contracts/script/ens.sh claim
ERRORS = {}  # selector -> name, filled lazily


class Chain:
    def __init__(self, rpc: str, key_file: Path, resolver: str, registry: str):
        self.rpc, self.key_file, self.resolver, self.registry = rpc, Path(key_file), resolver, registry
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
        if not os.access(self.key_file, os.R_OK):
            raise RuntimeError(f"key file {self.key_file} not readable")
        pk = "".join(self.key_file.read_text().split())
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
        """Other tools can share this key. Don't race them: wait while their cast/ens.sh runs."""
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

    def keccak_hex(self, hexdata: str) -> str:
        return self.cast("keccak", "0x" + hexdata.removeprefix("0x"))

    def keccak_str(self, s: str) -> str:
        """Always as hex: given the raw text, cast decodes a label like 0xab and takes --foo for a flag."""
        return self.keccak_hex(s.encode().hex())

    # -- MeetResolver reads
    def counts(self, label: str) -> tuple[bool, int, int, int]:
        out = self.call(self.resolver, "countsOf(bytes32)(bool,uint32,uint32,uint32)", self.keccak_str(label))
        v = out.split()
        return v[0] == "true", int(v[1]), int(v[2]), int(v[3])

    def meeting(self, mid: str) -> dict:
        out = self.call(self.resolver, "meetingOf(bytes32)(uint256,uint256,bool,bool,bool)", mid).split("\n")
        vals = [l.split()[0] for l in out]
        return {"exists": vals[2] == "true", "zk": vals[3] == "true", "voided": vals[4] == "true"}

    # -- meetings
    def record_would(self, mid: str, lha: str, lhb: str, tb: int, ev: str) -> str:
        """eth_call of record: "true" if these two meet for the first time. Raises RuntimeError on a revert."""
        self.load_key()
        return self.call(self.resolver, RECORD_SIG + "(bool)", mid, lha, lhb, str(tb), ev, frm=self.me)

    def record(self, mid: str, lha: str, lhb: str, tb: int, ev: str) -> dict:
        return self.send(self.resolver, RECORD_SIG, mid, lha, lhb, str(tb), ev)

    def mark_zk(self, mid: str) -> dict:
        return self.send(self.resolver, "markZkVerified(bytes32)", mid)

    # -- proofs. proof: 0x hex, inputs: "[0x..,0x..]"
    def verify_call(self, verifier: str, proof: str, inputs: str) -> str:
        return self.call(verifier, "verify(bytes,bytes32[])(bool)", proof, inputs)

    def verify_send(self, verifier: str, verify_log: str | None, proof: str, inputs: str) -> dict:
        """Through VerifyLog when there is one, it emits Verified. Else a plain tx to the verifier."""
        if verify_log:
            return self.send(verify_log, "verifyAndLog(address,bytes,bytes32[])", verifier, proof, inputs)
        return self.send(verifier, "verify(bytes,bytes32[])", proof, inputs)

    # -- claims: register(label, admin, no subregistry, resolver, 0, now + 90 d) then touch (= ens.sh claim)
    def register(self, label: str) -> str:
        self.load_key()
        exp = int(self.cast("block", "latest", "-f", "timestamp", "--rpc-url", self.rpc)) + NAME_TTL
        rc = self.send(self.registry, "register(string,address,address,address,uint256,uint64)",
                       label, self.me, "0x" + "0" * 40, self.resolver, "0", str(exp))
        return rc["transactionHash"]

    def touch(self, label: str) -> None:
        self.send(self.resolver, "touch(string)", label)
