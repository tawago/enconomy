import pytest
from fastapi.testclient import TestClient

from pop.main import Settings, create_app
from pop.store import SqliteStore
from tests.phones import Clock, Phone


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_client(clock, tmp_path):
    def make(allow_unattested: bool = False, **kw):
        kw.setdefault("issuer_key_file", str(tmp_path / "issuer.pem"))
        cfg = Settings(db=":memory:", allow_unattested=allow_unattested, now_ms=clock, data_dir=str(tmp_path), **kw)
        return TestClient(create_app(cfg, SqliteStore(":memory:")))
    return make


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def phones(client, clock):
    """Two enrolled (attested) phones: host A, guest B."""
    a, b = Phone(client, clock, "Alice", "Pixel 8"), Phone(client, clock, "Bob", "Galaxy S23")
    assert a.enroll().status_code == 200
    assert b.enroll().status_code == 200
    return a, b
