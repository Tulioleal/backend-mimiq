from __future__ import annotations


def test_internal_ready_marks_gpu_as_ready(client) -> None:
    response = client.post(
        "/internal/tts-ready",
        json={"endpoint": "http://tts.test:8000", "instance_id": "vast-123"},
        headers={"X-Internal-Key": "internal-test-secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["endpoint"] == "http://tts.test:8000"


def test_internal_offline_marks_gpu_as_offline(client) -> None:
    ready = client.post(
        "/internal/tts-ready",
        json={"endpoint": "http://tts.test:8000", "instance_id": "vast-123"},
        headers={"X-Internal-Key": "internal-test-secret"},
    )
    assert ready.status_code == 200

    offline = client.post(
        "/internal/tts-offline",
        json={"instance_id": "vast-123", "reason": "watchdog_timeout"},
        headers={"X-Internal-Key": "internal-test-secret"},
    )

    assert offline.status_code == 200
    assert offline.json()["status"] == "offline"
    assert offline.json()["detail"] == "watchdog_timeout"
