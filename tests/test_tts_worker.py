from __future__ import annotations

import asyncio

from models.gpu import TTSStreamMetrics
from services.tts_worker import TTSWorkerService


class FakeWebSocket:
    def __init__(self) -> None:
        self.json_messages: list[dict] = []
        self.byte_messages: list[bytes] = []
        self.closed = False

    async def send_json(self, message: dict) -> None:
        self.json_messages.append(message)

    async def send_bytes(self, message: bytes) -> None:
        self.byte_messages.append(message)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        del code, reason
        self.closed = True


def test_worker_service_dispatches_job_and_completes_result() -> None:
    async def run() -> None:
        service = TTSWorkerService()
        worker = FakeWebSocket()
        client = FakeWebSocket()

        await service.connect(worker)
        future = await service.send_job(
            job_id="gen-1",
            client_websocket=client,
            sample_bytes=b"sample-audio",
            text="Hola mundo.",
            language="es",
            slider_config={"temperature": 0.7},
        )

        assert worker.json_messages == [
            {
                "type": "synthesize",
                "job_id": "gen-1",
                "text": "Hola mundo.",
                "language": "es",
                "slider_config": {"temperature": 0.7},
                "speaker_wav_url": "/internal/jobs/gen-1/speaker.wav",
                "result_url": "/internal/jobs/gen-1/result",
            }
        ]
        assert await service.get_sample("gen-1") == b"sample-audio"

        await service.forward_audio_chunk(b"chunk-1")
        assert client.byte_messages == [b"chunk-1"]

        await service.complete_job(
            "gen-1",
            "gs://outputs/generations/gen-1.wav",
            TTSStreamMetrics(gpu_time_ms=123, rtf=0.5),
        )
        result = await future

        assert result.output_gcs_path == "gs://outputs/generations/gen-1.wav"
        assert result.gpu_time_ms == 123
        assert result.rtf == 0.5

    asyncio.run(run())
