"""Settings from the environment (.env.example). The core's key is pinned here and never fetched at runtime."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from backend.core import load_pub


@dataclass
class Settings:
    core_pubkey: bytes
    db: Path
    attest_key_file: Path
    chain_id: int = 11155111
    att_ttl_s: int = 900
    core_url: str = "http://127.0.0.1:8000"
    rpc: str = "https://ethereum-sepolia-rpc.publicnode.com"
    relayer_key_file: Path | None = None    # None: the relayer's own default
    relayer_dir: Path = Path(__file__).resolve().parent.parent / "relayer"

    @classmethod
    def from_env(cls) -> "Settings":
        raw = os.environ.get("SAFE_CORE_PRESENCE_PUBKEY", "")
        if not raw:
            raise ValueError("SAFE_CORE_PRESENCE_PUBKEY is not set: copy presence.pubkey from the core's GET /v1/config")
        pub = bytes.fromhex(raw)
        load_pub(pub)
        key = os.environ.get("SAFE_ATTEST_KEY_FILE", "")
        if not key:
            raise ValueError("SAFE_ATTEST_KEY_FILE is not set: point it at the key the deployed guard pins")
        relayer = os.environ.get("RELAYER_KEY_FILE", "")
        return cls(core_pubkey=pub,
                   db=Path(os.environ.get("SAFE_DB", "data/safe.sqlite")).expanduser(),
                   attest_key_file=Path(key).expanduser(),
                   chain_id=int(os.environ.get("SAFE_CHAIN_ID", "11155111")),
                   att_ttl_s=int(os.environ.get("SAFE_ATT_TTL_S", "900")),
                   core_url=os.environ.get("SAFE_CORE_URL", "http://127.0.0.1:8000").rstrip("/"),
                   rpc=os.environ.get("RPC", "https://ethereum-sepolia-rpc.publicnode.com"),
                   relayer_key_file=Path(relayer).expanduser() if relayer else None)
