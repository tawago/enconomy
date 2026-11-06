from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from tests.helpers import CORE_PUB, Clock, FakeChain


@pytest.fixture(autouse=True)
def no_shell(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError(f"a test shelled out: {a}")
    monkeypatch.setattr(subprocess, "run", refuse)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def chain():
    return FakeChain()


@pytest.fixture
def settings(tmp_path):
    return Settings(core_pubkey=CORE_PUB, db=tmp_path / "ens.sqlite", key_file=tmp_path / "no.key", rpc="http://no",
                    core_url="http://core.invalid", deployments=tmp_path / "no.json")


@pytest.fixture
def client(settings, chain, clock):
    with TestClient(create_app(settings, chain, clock)) as c:
        yield c
