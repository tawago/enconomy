"""Settings from the environment (.env.example). The core's key is pinned here and never fetched at runtime."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from backend.core import device_id, load_pub

DEVICE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"{name} is not set, see .env.example")
    return value


def admin_device_id(raw: str) -> str:
    """The phone shows its device id, not its key. record_problem checks device_id == sha256(pubkey)[:16] on every
    record, so either form names the same key."""
    raw = raw.strip().lower().removeprefix("0x")
    if DEVICE_ID_RE.fullmatch(raw):
        return raw
    pub = bytes.fromhex(raw)
    load_pub(pub)
    return device_id(pub)


@dataclass
class Settings:
    core_pubkey: bytes
    admin_device: str
    admin_passcode: str
    ens_dir: Path
    db: Path = Path("data/onboarding.sqlite")
    org: str = "blob.eth"
    chain_id: int = 11155111
    web_app_url: str = "http://localhost:8001/app/"
    public_url: str = "http://localhost:8400"

    @property
    def web_origin(self) -> str:
        """The only origin that may post a record from a browser: the core's web app."""
        u = urlsplit(self.web_app_url)
        return f"{u.scheme}://{u.netloc}"

    @classmethod
    def from_env(cls) -> "Settings":
        pub = bytes.fromhex(_required("ONBOARD_CORE_PRESENCE_PUBKEY"))
        load_pub(pub)
        return cls(core_pubkey=pub,
                   admin_device=admin_device_id(_required("ONBOARD_ADMIN_DEVICE")),
                   admin_passcode=_required("ONBOARD_ADMIN_PASSCODE"),
                   ens_dir=Path(_required("ONBOARD_ENS_DIR")).expanduser().resolve(),
                   db=Path(os.environ.get("ONBOARD_DB", "data/onboarding.sqlite")).expanduser(),
                   org=os.environ.get("ONBOARD_ORG", "blob.eth"),
                   chain_id=int(os.environ.get("ONBOARD_CHAIN_ID", "11155111")),
                   web_app_url=os.environ.get("ONBOARD_WEB_APP_URL", "http://localhost:8001/app/"),
                   public_url=os.environ.get("ONBOARD_PUBLIC_URL", "http://localhost:8400").rstrip("/"))
