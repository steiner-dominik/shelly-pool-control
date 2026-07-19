"""API tests against the simulator (no hardware needed)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(client):
    """Set up the initial admin and return an authenticated client."""
    r = client.post("/api/auth/setup",
                    json={"username": "admin", "password": "test-password-1"})
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf"]
    client.headers["X-CSRF-Token"] = csrf
    return client


def test_health(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_setup_required_then_auth_flow(admin):
    r = admin.get("/api/auth/state")
    body = r.json()
    assert body["authenticated"] is True
    assert body["role"] == "admin"
    assert body["setup_required"] is False


def test_second_setup_rejected(admin):
    r = admin.post("/api/auth/setup",
                   json={"username": "x", "password": "test-password-2"})
    assert r.status_code == 409


def test_unauthenticated_rejected():
    with TestClient(app) as anon:
        assert anon.get("/api/status").status_code == 401
        assert anon.post("/api/control/mode",
                         json={"mode": "off"}).status_code == 401


def test_csrf_enforced(admin):
    saved = admin.headers.pop("X-CSRF-Token")
    r = admin.post("/api/control/mode", json={"mode": "auto"})
    admin.headers["X-CSRF-Token"] = saved
    assert r.status_code == 403


def test_status_and_mode_roundtrip(admin):
    r = admin.get("/api/status")
    assert r.status_code == 200
    r = admin.post("/api/control/mode", json={"mode": "boost"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = admin.get("/api/status")
    assert r.json()["status"]["mode"] == "boost"
    r = admin.post("/api/control/mode", json={"mode": "auto"})
    assert r.status_code == 200


def test_config_validation(admin):
    r = admin.put("/api/config", json={"changes": {"dt_start": 99999}})
    assert r.status_code == 400
    r = admin.put("/api/config", json={"changes": {"nonexistent_key": 1}})
    assert r.status_code == 400
    r = admin.put("/api/config", json={"changes": {"mat_overtemp_action": "explode"}})
    assert r.status_code == 400


def test_config_apply_and_confirm(admin):
    r = admin.put("/api/config", json={"changes": {"dt_start": 4.5}})
    assert r.status_code == 200
    body = r.json()
    assert body["confirmed"] is True          # simulator confirms instantly
    r = admin.get("/api/config")
    values = r.json()["values"]
    assert values["dt_start"]["value"] == 4.5
    assert values["dt_start"]["pending"] is False


def test_manual_run_and_reset(admin):
    r = admin.post("/api/control/run", json={"duration_min": 5})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = admin.get("/api/status")
    assert r.json()["status"]["mode"] == "force_on"
    r = admin.post("/api/control/mode", json={"mode": "auto"})
    assert r.status_code == 200


def test_emergency_stop(admin):
    r = admin.post("/api/control/estop")
    assert r.status_code == 200
    r = admin.get("/api/status")
    assert r.json()["status"]["relay"] is False
    admin.post("/api/control/mode", json={"mode": "auto"})


def test_users_crud(admin):
    r = admin.post("/api/users", json={"username": "viewer1",
                                       "password": "viewer-pass-1",
                                       "role": "viewer"})
    assert r.status_code == 200
    users = admin.get("/api/users").json()
    v = next(u for u in users if u["username"] == "viewer1")

    # viewer can read but not control
    with TestClient(app) as vc:
        r = vc.post("/api/auth/login", json={"username": "viewer1",
                                             "password": "viewer-pass-1"})
        assert r.status_code == 200
        vc.headers["X-CSRF-Token"] = r.json()["csrf"]
        assert vc.get("/api/status").status_code == 200
        assert vc.post("/api/control/mode",
                       json={"mode": "off"}).status_code == 403
        assert vc.get("/api/config").status_code == 403

    r = admin.delete(f"/api/users/{v['id']}")
    assert r.status_code == 200


def test_backup_roundtrip(admin):
    r = admin.post("/api/backup/create")
    assert r.status_code == 200
    name = r.json()["name"]
    listed = admin.get("/api/backup/list").json()
    assert any(b["name"] == name for b in listed)
    blob = admin.get(f"/api/backup/download/{name}")
    assert blob.status_code == 200
    assert blob.headers["content-type"] == "application/zip"
    files = {"file": (name, blob.content, "application/zip")}
    r = admin.post("/api/backup/restore", files=files)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_backup_schedule(admin):
    r = admin.put("/api/backup/schedule",
                  json={"enabled": True, "time": "03:30", "keep": 7})
    assert r.status_code == 200
    r = admin.get("/api/backup/schedule")
    assert r.json()["enabled"] is True
    r = admin.put("/api/backup/schedule",
                  json={"enabled": True, "time": "25:99", "keep": 7})
    assert r.status_code == 400


def test_history_and_events(admin):
    assert admin.get("/api/history?range=day").status_code == 200
    assert admin.get("/api/history?range=bogus").status_code == 400
    assert admin.get("/api/events").status_code == 200
    assert admin.get("/api/audit").status_code == 200


def test_sim_fault_injection(admin):
    r = admin.post("/api/sim/sensor", json={"slot": "water_a", "dead": True})
    assert r.status_code == 200
    r = admin.post("/api/sim/reset")
    assert r.status_code == 200


def test_login_rate_limit():
    with TestClient(app) as anon:
        for _ in range(6):
            r = anon.post("/api/auth/login",
                          json={"username": "nobody", "password": "wrong-pass"})
        assert r.status_code in (401, 429)
        r = anon.post("/api/auth/login",
                      json={"username": "nobody", "password": "wrong-pass"})
        assert r.status_code == 429
