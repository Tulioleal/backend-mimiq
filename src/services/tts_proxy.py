from __future__ import annotations

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.exceptions import GPUNotReadyError
from models.generation import GenerationCreateInput
from models.gpu import GPUStatus
from models.websocket import AcceptedMessage, CompletedMessage, StatusMessage
from services.generation_service import GenerationService
from services.gpu import GPUOrchestrator
from services.llm import LLMPreprocessor
from services.storage import StorageService
from services.tts_worker import TTSWorkerService
from services.voice_service import VoiceService


class TTSProxyService:
    def __init__(
        self,
        settings: Settings,
        llm: LLMPreprocessor,
        storage: StorageService,
        gpu: GPUOrchestrator,
        tts_worker: TTSWorkerService,
        voices: VoiceService,
        generations: GenerationService,
    ):
        self.settings = settings
        self.llm = llm
        self.storage = storage
        self.gpu = gpu
        self.tts_worker = tts_worker
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
        await self.generations.start_metric(session, generation.id)
        await session.commit()

        await websocket.send_json(
            AcceptedMessage(generation_id=generation.id, rewritten_text=rewritten_text).model_dump()
        )

        sample_bytes = await self.storage.download_bytes(voice.gcs_path)
        result_future = await self.tts_worker.send_job(
            job_id=generation.id,
            client_websocket=websocket,
            sample_bytes=sample_bytes,
            text=rewritten_text,
            language=payload.language,
            slider_config=payload.slider_config.model_dump(),
        )
        result = await result_future

        await websocket.send_json(
            CompletedMessage(
                generation_id=generation.id,
                output_gcs_path=result.output_gcs_path,
                gpu_time_ms=result.gpu_time_ms,
                rtf=result.rtf,
            ).model_dump()
        )
