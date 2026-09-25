from pop import constants as K


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["proto"] == "pop-v1"


def test_time(client, clock):
    assert client.get("/v1/time").json() == {"server_ms": clock()}


def test_config(client):
    c = client.get("/v1/config").json()
    assert c["proto"] == "pop-v1" and c["n_null"] == 64 and c["near_cm"] == 60 and c["band_hz"] == [2000, 18000]
    assert c["b_play_s"] == 0.95 and c["capture_s"] == 2.5 and c["allow_unattested"] is False
    assert set(K.table()) <= set(c)


def test_unknown_route_error_shape(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
