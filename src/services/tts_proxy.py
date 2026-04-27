from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession
from websockets.asyncio.client import connect as websocket_connect

from core.config import Settings
from core.exceptions import GPUNotReadyError, UpstreamTTSError
from models.generation import GenerationCreateInput
from models.gpu import GPUStatus, TTSStreamMetrics, UpstreamStartPayload
from models.websocket import AcceptedMessage, CompletedMessage, StatusMessage
from services.generation_service import GenerationService
from services.gpu import GPUOrchestrator
from services.llm import LLMPreprocessor
from services.storage import StorageService
from services.voice_service import VoiceService

logger = logging.getLogger(__name__)


class TTSProxyService:
    def __init__(
        self,
        settings: Settings,
        llm: LLMPreprocessor,
        storage: StorageService,
        gpu: GPUOrchestrator,
        voices: VoiceService,
        generations: GenerationService,
    ):
        self.settings = settings
        self.llm = llm
        self.storage = storage
        self.gpu = gpu
        self.voices = voices
        self.generations = generations

    async def proxy_generation(
        self,
        websocket: WebSocket,
        session: AsyncSession,
        payload: GenerationCreateInput,
    ) -> None:
        status = await self.gpu.ensure_boot_requested(session)
        await websocket.send_json(StatusMessage(status=status.status, detail=status.detail).model_dump())
        if status.status is not GPUStatus.READY:
            raise GPUNotReadyError(status)

        voice = await self.voices.get_voice(session, payload.voice_id)
        if voice is None:
            raise ValueError("Voice not found.")

        rewritten_text = await self.llm.rewrite_text(payload.original_text, payload.style_prompt)
        generation = await self.generations.create_generation(session, payload)
        metric = await self.generations.start_metric(session, generation.id)
        await session.commit()

        await websocket.send_json(
            AcceptedMessage(generation_id=generation.id, rewritten_text=rewritten_text).model_dump()
        )

        sample_bytes = await self.storage.download_bytes(voice.gcs_path)
        audio_bytes, metrics = await self._stream_upstream_audio(
            websocket,
            session,
            rewritten_text,
            payload.language,
            payload.slider_config.model_dump(),
            sample_bytes,
        )

        output_gcs_path = await self.storage.upload_output(generation.id, audio_bytes)
        generation = await self.generations.get_generation(session, generation.id)
        if generation is None:
            raise RuntimeError("Generation disappeared before completion.")

        generation_metric = generation.metric or metric
        await self.generations.complete_generation(
            session,
            generation,
            generation_metric,
            output_gcs_path,
            metrics.gpu_time_ms,
            metrics.rtf,
        )

        await websocket.send_json(
            CompletedMessage(
                generation_id=generation.id,
                output_gcs_path=output_gcs_path,
                gpu_time_ms=metrics.gpu_time_ms,
                rtf=metrics.rtf,
            ).model_dump()
        )

    async def _stream_upstream_audio(
        self,
        client_websocket: WebSocket,
        session: AsyncSession,
        rewritten_text: str,
        language: str,
        slider_config: dict[str, float],
        sample_bytes: bytes,
    ) -> tuple[bytes, TTSStreamMetrics]:
        endpoint = await self.gpu.get_streaming_endpoint(session)
        upstream_url = self._build_upstream_ws_url(endpoint)
        output = bytearray()
        metrics = TTSStreamMetrics()

        async with websocket_connect(upstream_url, max_size=None) as upstream:
            start_payload = UpstreamStartPayload(
                text=rewritten_text,
                language=language,
                slider_config=slider_config,
            )
            await upstream.send(start_payload.model_dump_json())
            await upstream.send(sample_bytes)
            await upstream.send(json.dumps({"event": "end_sample"}))

            async for message in upstream:
                if isinstance(message, bytes):
                    output.extend(message)
                    await client_websocket.send_bytes(message)
                    continue

                event = json.loads(message)
                event_type = event.get("event") or event.get("type")
                if event_type == "metrics":
                    metrics = TTSStreamMetrics.model_validate(event)
                elif event_type == "error":
                    raise UpstreamTTSError(event.get("message") or "Upstream TTS error")
                elif event_type == "completed":
                    metrics = TTSStreamMetrics(
                        gpu_time_ms=event.get("gpu_time_ms", metrics.gpu_time_ms),
                        rtf=event.get("rtf", metrics.rtf),
                    )
                    break
                else:
                    logger.info("Ignoring upstream event", extra={"event": event})

        if not output:
            raise UpstreamTTSError("Upstream TTS service returned no audio chunks.")
        return bytes(output), metrics

    def _build_upstream_ws_url(self, endpoint: str) -> str:
        parsed = urlparse(endpoint)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = self.settings.tts_ws_path
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{scheme}://{parsed.netloc}{path}"
