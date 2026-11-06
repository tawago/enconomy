from __future__ import annotations

import subprocess
import urllib.request

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from tests.helpers import CORE_PUB, NOW_MS, Phone


@pytest.fixture(autouse=True)
def no_shell(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError(f"a test shelled out: {a}")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def attest_key(tmp_path):
    """A throwaway key, written like the real one."""
    sk = ec.generate_private_key(ec.SECP256R1())
    (tmp_path / "attest.pem").write_bytes(sk.private_bytes(serialization.Encoding.PEM,
                                                           serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
    return sk


@pytest.fixture
def settings(tmp_path, attest_key):
    return Settings(core_pubkey=CORE_PUB, db=tmp_path / "safe.sqlite", attest_key_file=tmp_path / "attest.pem",
                    core_url="http://core.invalid", rpc="http://no")


@pytest.fixture
def wakes():
    return []


@pytest.fixture
def client(settings, wakes):
    with TestClient(create_app(settings, now_ms=lambda: NOW_MS, wake=lambda: wakes.append(1))) as c:
        yield c


@pytest.fixture
def phones():
    return Phone(), Phone()
