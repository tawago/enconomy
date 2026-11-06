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
    rp_id: str
    app_id: str
    signing_key_file: Path
    sidecar: str = "http://127.0.0.1:8787"
    portal: str = "https://developer.world.org"
    return_to: str = "enconomy://worldid"

    @classmethod
    def from_env(cls) -> "Settings":
        def need(name: str, why: str) -> str:
            if not (v := os.environ.get(name, "")):
                raise ValueError(f"{name} is not set: {why}")
            return v
        pub = bytes.fromhex(need("WID_CORE_PRESENCE_PUBKEY", "copy presence.pubkey from the core's GET /v1/config"))
        load_pub(pub)
        return cls(core_pubkey=pub,
                   db=Path(os.environ.get("WID_DB", "data/world-id.sqlite")).expanduser(),
                   rp_id=need("WID_RP_ID", "from the World ID developer portal"),
                   app_id=need("WID_APP_ID", "from the World ID developer portal"),
                   signing_key_file=Path(need("WID_SIGNING_KEY_FILE", "point it at the RP signing key")).expanduser(),
                   sidecar=os.environ.get("WID_SIDECAR", "http://127.0.0.1:8787").rstrip("/"),
                   portal=os.environ.get("WID_PORTAL", "https://developer.world.org").rstrip("/"),
                   return_to=os.environ.get("WID_RETURN_TO", "enconomy://worldid"))
