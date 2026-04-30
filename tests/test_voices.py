from __future__ import annotations

from models.voice import AudioHealthIssue, AudioHealthReport


class FailingAudioHealthAnalyzer:
    async def analyze_upload(self, upload) -> tuple[bytes, AudioHealthReport]:
        content = await upload.read()
        return content, AudioHealthReport(
            passed=False,
            duration_seconds=194.27,
            average_db=-18.45,
            peak_db=0.0,
            noise_floor_db=-56.13,
            estimated_snr_db=37.41,
            clipped_ratio=0.000001,
            issues=[
                AudioHealthIssue(
                    code="clipping_detected",
                    message="Audio appears clipped or distorted.",
                )
            ],
            recommendations=["Lower the recording gain to avoid clipping."],
        )


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


def test_create_voice_allows_failed_health_report(client) -> None:
    login = client.post("/api/auth/login", json={"adminKey": "test-admin-key"})
    assert login.status_code == 200

    client.app.state.services.audio_health = FailingAudioHealthAnalyzer()

    create = client.post(
        "/api/voices",
        data={"name": "Imperfect sample"},
        files={"audio": ("voice.ogg", b"fake-clipped-audio-bytes", "audio/ogg")},
    )

    assert create.status_code == 200
    voice_payload = create.json()
    assert voice_payload["name"] == "Imperfect sample"
    assert voice_payload["health_report"]["passed"] is False
    assert voice_payload["health_report"]["issues"][0]["code"] == "clipping_detected"

    listing = client.get("/api/voices")
    assert listing.status_code == 200
    assert len(listing.json()) == 1
