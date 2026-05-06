from __future__ import annotations

from starlette.websockets import WebSocketDisconnect


def test_internal_worker_ws_marks_gpu_as_ready(client) -> None:
    with client.websocket_connect(
        "/internal/tts-worker/ws?instance_id=vast-123",
        headers={"X-Internal-Key": "internal-test-secret"},
    ):
        status_response = client.get(
            "/api/status/gpu",
            headers={"X-Admin-Key": "test-admin-key"},
        )

        assert status_response.status_code == 200
        assert status_response.json()["status"] == "ready"
        assert status_response.json()["endpoint"] is None


def test_internal_worker_ws_requires_internal_key(client) -> None:
    try:
        with client.websocket_connect("/internal/tts-worker/ws"):
            raise AssertionError("Worker connected without internal key")
    except WebSocketDisconnect as exc:
        assert exc.code == 1008


def test_internal_worker_disconnect_marks_gpu_as_offline(client) -> None:
    with client.websocket_connect(
        "/internal/tts-worker/ws?instance_id=vast-123",
        headers={"X-Internal-Key": "internal-test-secret"},
    ):
        pass

    status_response = client.get(
        "/api/status/gpu",
        headers={"X-Admin-Key": "test-admin-key"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "offline"
    assert status_response.json()["detail"] == "TTS worker disconnected."


def test_internal_offline_marks_gpu_as_offline(client) -> None:
    with client.websocket_connect(
        "/internal/tts-worker/ws?instance_id=vast-123",
        headers={"X-Internal-Key": "internal-test-secret"},
    ):
        offline = client.post(
            "/internal/tts-offline",
            json={"instance_id": "vast-123", "reason": "watchdog_timeout"},
            headers={"X-Internal-Key": "internal-test-secret"},
        )

        assert offline.status_code == 200
        assert offline.json()["status"] == "offline"
        assert offline.json()["detail"] == "watchdog_timeout"
