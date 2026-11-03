from app.core.config import settings
from app.core.auth import attempts


def test_session_login_logout_and_audit_identity(client, monkeypatch):
    attempts.clear()
    monkeypatch.setattr(settings, "auth_password", "a-long-test-password")
    assert client.get("/api/session").json()["authenticated"] is False
    assert (
        client.post(
            "/api/session", json={"username": "reviewer", "password": "wrong"}
        ).status_code
        == 401
    )
    response = client.post(
        "/api/session",
        json={"username": "reviewer", "password": "a-long-test-password"},
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/api/documents").status_code == 200
    material = client.post(
        "/api/materials", json={"standard_name": "Synthetic review product"}
    )
    assert material.status_code == 201
    assert client.get("/api/audit").json()[0]["actor"] == "reviewer"
    assert client.delete("/api/session").status_code == 200
    assert client.get("/api/documents").status_code == 401


def test_login_throttling(client, monkeypatch):
    attempts.clear()
    monkeypatch.setattr(settings, "auth_password", "a-long-test-password")
    for _ in range(10):
        assert (
            client.post(
                "/api/session", json={"username": "reviewer", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/session", json={"username": "reviewer", "password": "wrong"}
        ).status_code
        == 429
    )
    attempts.clear()


def test_forged_cookie_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_password", "a-long-test-password")
    client.cookies.set("ed_session", "forged.signature")
    assert client.get("/api/documents").status_code == 401


def test_unicode_credentials_rejected_cleanly(client, monkeypatch):
    attempts.clear()
    monkeypatch.setattr(settings, "auth_password", "a-long-test-password")
    assert (
        client.post(
            "/api/session", json={"username": "石綿", "password": "wrong"}
        ).status_code
        == 401
    )
