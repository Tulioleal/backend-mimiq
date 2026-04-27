from __future__ import annotations


def test_create_list_download_and_delete_voice(client) -> None:
    login = client.post("/api/auth/login", json={"adminKey": "test-admin-key"})
    assert login.status_code == 200

    create = client.post(
        "/api/voices",
        data={"name": "Ana"},
        files={"audio": ("voice.wav", b"fake-audio-bytes", "audio/wav")},
    )
    assert create.status_code == 200
    voice_payload = create.json()
    assert voice_payload["name"] == "Ana"
    assert voice_payload["health_report"]["passed"] is True

    listing = client.get("/api/voices")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    audio = client.get(f"/api/voices/{voice_payload['id']}/audio")
    assert audio.status_code == 200
    assert audio.content == b"fake-audio-bytes"

    delete = client.delete(f"/api/voices/{voice_payload['id']}")
    assert delete.status_code == 204

    listing_after_delete = client.get("/api/voices")
    assert listing_after_delete.status_code == 200
    assert listing_after_delete.json() == []
