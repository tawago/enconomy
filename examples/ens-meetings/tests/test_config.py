"""The pin is required and checked, and the real backend wiring starts with no chain traffic when nothing is pending."""
import pytest
from fastapi.testclient import TestClient

from backend.chain import Chain
from backend.config import Settings
from backend.main import create_app
from tests.helpers import VECTOR


def test_pin_required(monkeypatch):
    monkeypatch.delenv("ENS_CORE_PRESENCE_PUBKEY", raising=False)
    with pytest.raises(ValueError, match="ENS_CORE_PRESENCE_PUBKEY"):
        Settings.from_env()
    for bad in ("zz", "04ab"):
        monkeypatch.setenv("ENS_CORE_PRESENCE_PUBKEY", bad)
        with pytest.raises(ValueError):
            Settings.from_env()


def test_real_wiring_reads_the_example_deployments(monkeypatch, tmp_path):
    monkeypatch.setenv("ENS_CORE_PRESENCE_PUBKEY", VECTOR["pubkey_hex"])
    monkeypatch.setenv("ENS_DB", str(tmp_path / "sub" / "ens.sqlite"))
    monkeypatch.delenv("ENS_DEPLOYMENTS", raising=False)
    s = Settings.from_env()
    assert s.statement_max_age_s == 3600 and s.key_file.name == "ens-sepolia.key"
    app = create_app(s)   # conftest refuses any subprocess, so this proves no cast runs
    with TestClient(app) as c:
        assert c.get("/health").json() == {"ok": True}
        assert isinstance(app.state.worker.chain, Chain)
        assert app.state.worker.chain.resolver == s.deployed()["meetResolver"]
