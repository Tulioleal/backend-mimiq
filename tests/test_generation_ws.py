from __future__ import annotations

from starlette.websockets import WebSocketDisconnect


def test_generation_websocket_dispatches_startup_when_offline(client) -> None:
    login = client.post("/api/auth/login", json={"adminKey": "test-admin-key"})
    assert login.status_code == 200

    gpu = client.app.state.services.gpu

    with client.websocket_connect("/ws/generations/stream") as websocket:
        websocket.send_json(
            {
                "type": "start_generation",
                "voice_id": "voice-1",
                "original_text": "Hola mundo.",
                "style_prompt": "neutral",
                "language": "es",
                "slider_config": {
                    "temperature": 0.7,
                    "speech_speed": 1.0,
                    "repetition_penalty": 2.0,
                },
            }
        )

        status_message = websocket.receive_json()
        error_message = websocket.receive_json()

        assert status_message["type"] == "status"
        assert status_message["status"] == "booting"
        assert "workflow dispatched" in status_message["detail"].lower()
        assert error_message["type"] == "error"
        assert "workflow dispatched" in error_message["message"].lower()

        try:
            websocket.receive_json()
        except WebSocketDisconnect as exc:
            assert exc.code == 1013

    assert gpu.startup_dispatches == 1


def test_generation_websocket_accepts_one_time_ticket(client) -> None:
    login = client.post("/api/auth/login", json={"adminKey": "test-admin-key"})
    assert login.status_code == 200
    ticket_response = client.post("/api/auth/ws-ticket")
    assert ticket_response.status_code == 200
    ticket = ticket_response.json()["ticket"]
    client.cookies.clear()

    with client.websocket_connect(f"/ws/generations/stream?ticket={ticket}") as websocket:
        websocket.send_json(
            {
                "type": "start_generation",
                "voice_id": "voice-1",
                "original_text": "Hola mundo.",
                "style_prompt": "neutral",
                "language": "es",
                "slider_config": {
                    "temperature": 0.7,
                    "speech_speed": 1.0,
                    "repetition_penalty": 2.0,
                },
            }
        )

        status_message = websocket.receive_json()
        assert status_message["type"] == "status"
        assert status_message["status"] == "booting"


def test_generation_websocket_ticket_is_one_time_use(client) -> None:
    login = client.post("/api/auth/login", json={"adminKey": "test-admin-key"})
    assert login.status_code == 200
    ticket_response = client.post("/api/auth/ws-ticket")
    assert ticket_response.status_code == 200
    ticket = ticket_response.json()["ticket"]
    client.cookies.clear()

    with client.websocket_connect(f"/ws/generations/stream?ticket={ticket}") as websocket:
        websocket.close()

    try:
        with client.websocket_connect(f"/ws/generations/stream?ticket={ticket}"):
            raise AssertionError("Reused ticket unexpectedly connected")
    except WebSocketDisconnect as exc:
        assert exc.code == 1008
