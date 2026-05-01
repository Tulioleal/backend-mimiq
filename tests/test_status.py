from __future__ import annotations


def test_status_requires_authentication(client) -> None:
    response = client.get("/api/status/gpu")
    assert response.status_code == 401


def test_status_returns_gpu_state_for_authenticated_user(client) -> None:
    client.post("/api/auth/login", json={"adminKey": "test-admin-key"})
    response = client.get("/api/status/gpu")

    assert response.status_code == 200
    assert response.json()["status"] == "offline"


def test_status_returns_ready_after_internal_registration(client) -> None:
    client.post("/api/auth/login", json={"adminKey": "test-admin-key"})
    ready = client.post(
        "/internal/tts-ready",
        json={"endpoint": "http://tts.test:8000", "instance_id": "vast-123"},
        headers={"X-Internal-Key": "internal-test-secret"},
    )
    assert ready.status_code == 200

    response = client.get("/api/status/gpu")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"

