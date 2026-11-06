from __future__ import annotations

import json
import subprocess
import urllib.request

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from tests.helpers import CORE_PUB, Clock, FakeChain, FakeHttp


@pytest.fixture(autouse=True)
def no_shell(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError(f"a test shelled out: {a}")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    for e in ("BRIDGE_CONFIG", "ETH_RPC", "ENS_KEY_FILE", "ENS_DEPLOYMENTS", "ENS_ZK_DEPLOYMENTS", "ENS_DB", "BRIDGE_LOG",
              "ENS_CORE_URL"):
        monkeypatch.delenv(e, raising=False)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def chain():
    return FakeChain()


@pytest.fixture
def http():
    return FakeHttp()


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "dep.json").write_text(json.dumps({"meetResolver": "0x" + "11" * 20, "registry": "0x" + "22" * 20,
                                                   "parent": "enconomy.eth"}))
    (tmp_path / "zk.json").write_text(json.dumps({"phoneVerifier": "0x" + "33" * 20, "verifyLog": "0x" + "44" * 20}))
    return Settings(core_pubkey=CORE_PUB, db=tmp_path / "ens.sqlite", key_file=tmp_path / "no.key", rpc="http://no",
                    core_url="http://core.invalid", deployments=tmp_path / "dep.json",
                    zk_deployments=tmp_path / "zk.json", log=tmp_path / "log.jsonl")


@pytest.fixture
def client(settings, chain, clock, http):
    with TestClient(create_app(settings, chain, clock, http)) as c:
        yield c
