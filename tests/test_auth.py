from __future__ import annotations


def test_login_sets_http_only_cookie(client) -> None:
    response = client.post("/api/auth/login", json={"adminKey": "test-admin-key"})

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert "httponly" in response.headers["set-cookie"].lower()


def test_invalid_login_is_rejected(client) -> None:
    response = client.post("/api/auth/login", json={"adminKey": "wrong-key"})

    assert response.status_code == 401


def test_session_uses_cookie_after_login(client) -> None:
    login = client.post("/api/auth/login", json={"adminKey": "test-admin-key"})
    assert login.status_code == 200

    response = client.get("/api/auth/session")
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
