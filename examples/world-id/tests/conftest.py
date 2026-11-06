from __future__ import annotations

import subprocess
import urllib.request

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from tests.helpers import CORE_PUB, Clock, FakeWorld, Phone


@pytest.fixture(autouse=True)
def no_shell(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError(f"a test shelled out: {a}")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "rp.key").write_text("0x" + "ab" * 32)
    return Settings(core_pubkey=CORE_PUB, db=tmp_path / "world-id.sqlite", rp_id="rp_0123456789abcdef",
                    app_id="app_test", signing_key_file=tmp_path / "rp.key")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def fw():
    return FakeWorld()


@pytest.fixture
def client(settings, clock, fw):
    async def nosleep(_s):
        return None
    with TestClient(create_app(settings, now_ms=clock, transport=httpx.MockTransport(fw), sleep=nosleep)) as c:
        yield c


@pytest.fixture
def phones(client, clock):
    return Phone(client, clock, "A"), Phone(client, clock, "B")
