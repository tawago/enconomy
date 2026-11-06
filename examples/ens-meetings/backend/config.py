"""Settings from the environment (.env.example). The core's key is pinned here and never fetched at runtime."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from backend.core import load_pub

HERE = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    core_pubkey: bytes
    db: Path
    key_file: Path
    rpc: str
    core_url: str
    deployments: Path
    statement_max_age_s: int = 3600
    zk_deployments: Path | None = None   # None: the bridge's default next to deployments
    log: Path | None = None              # None: the bridge's default

    @classmethod
    def from_env(cls) -> "Settings":
        raw = os.environ.get("ENS_CORE_PRESENCE_PUBKEY", "")
        if not raw:
            raise ValueError("ENS_CORE_PRESENCE_PUBKEY is not set: copy presence.pubkey from the core's GET /v1/config")
        pub = bytes.fromhex(raw)
        load_pub(pub)
        return cls(core_pubkey=pub,
                   db=Path(os.environ.get("ENS_DB", "data/ens.sqlite")).expanduser(),
                   key_file=Path(os.environ.get("ENS_KEY_FILE", "~/.enconomy/ens-sepolia.key")).expanduser(),
                   rpc=os.environ.get("ETH_RPC", "https://ethereum-sepolia-rpc.publicnode.com"),
                   core_url=os.environ.get("ENS_CORE_URL", "http://127.0.0.1:8000").rstrip("/"),
                   deployments=Path(os.environ.get("ENS_DEPLOYMENTS", HERE / "contracts/deployments/sepolia.json")),
                   statement_max_age_s=int(os.environ.get("ENS_STATEMENT_MAX_AGE_S", "3600")),
                   zk_deployments=Path(os.environ.get("ENS_ZK_DEPLOYMENTS", HERE / "contracts/deployments/zk-sepolia.json")),
                   log=Path(os.environ["BRIDGE_LOG"]) if os.environ.get("BRIDGE_LOG") else None)

    def deployed(self) -> dict:
        return json.loads(self.deployments.read_text())
