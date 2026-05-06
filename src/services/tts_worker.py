from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import WebSocket

from core.exceptions import UpstreamTTSError
from models.gpu import TTSStreamMetrics


@dataclass(slots=True)
class TTSJobResult:
    output_gcs_path: str
    gpu_time_ms: int | None
    rtf: float | None


@dataclass(slots=True)
class PendingTTSJob:
    job_id: str
    sample_bytes: bytes
    client_websocket: WebSocket
    future: asyncio.Future[TTSJobResult]


class TTSWorkerService:
    def __init__(self) -> None:
        self._worker: WebSocket | None = None
        self._active_job: PendingTTSJob | None = None
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        async with self._lock:
            previous = self._worker
            self._worker = websocket
            if previous is not None and previous is not websocket:
                await previous.close(code=1012, reason="Replaced by a newer TTS worker")

    async def disconnect(self, websocket: WebSocket) -> bool:
        async with self._lock:
            if self._worker is not websocket:
                return False
            self._worker = None
            if self._active_job is not None and not self._active_job.future.done():
                self._active_job.future.set_exception(UpstreamTTSError("TTS worker disconnected"))
            self._active_job = None
            return True

    async def is_connected(self) -> bool:
        async with self._lock:
            return self._worker is not None

    async def send_job(
        self,
        *,
        job_id: str,
        client_websocket: WebSocket,
        sample_bytes: bytes,
        text: str,
        language: str,
        slider_config: dict[str, float],
    ) -> asyncio.Future[TTSJobResult]:
        async with self._lock:
            if self._worker is None:
                raise UpstreamTTSError("No active TTS worker is connected.")
            if self._active_job is not None:
                raise UpstreamTTSError("TTS worker is busy.")

            loop = asyncio.get_running_loop()
            future: asyncio.Future[TTSJobResult] = loop.create_future()
            self._active_job = PendingTTSJob(
                job_id=job_id,
                sample_bytes=sample_bytes,
                client_websocket=client_websocket,
                future=future,
            )
            await self._worker.send_json(
                {
                    "type": "synthesize",
                    "job_id": job_id,
                    "text": text,
                    "language": language,
                    "slider_config": slider_config,
                    "speaker_wav_url": f"/internal/jobs/{job_id}/speaker.wav",
                    "result_url": f"/internal/jobs/{job_id}/result",
                }
            )
            return future

    async def get_sample(self, job_id: str) -> bytes | None:
        async with self._lock:
            if self._active_job is None or self._active_job.job_id != job_id:
                return None
            return self._active_job.sample_bytes

    async def forward_audio_chunk(self, chunk: bytes) -> None:
        async with self._lock:
            job = self._active_job
        if job is None:
            return
        try:
            await job.client_websocket.send_bytes(chunk)
        except Exception:
            await self.fail_active_job("Client disconnected during TTS streaming")

    async def fail_active_job(self, message: str) -> None:
        async with self._lock:
            job = self._active_job
            self._active_job = None
        if job is not None and not job.future.done():
            job.future.set_exception(UpstreamTTSError(message))

    async def complete_job(
        self,
        job_id: str,
        output_gcs_path: str,
        metrics: TTSStreamMetrics,
    ) -> TTSJobResult | None:
        async with self._lock:
            if self._active_job is None or self._active_job.job_id != job_id:
                return None
            job = self._active_job
            self._active_job = None

        result = TTSJobResult(
            output_gcs_path=output_gcs_path,
            gpu_time_ms=metrics.gpu_time_ms,
            rtf=metrics.rtf,
        )
        if not job.future.done():
            job.future.set_result(result)
        return result
