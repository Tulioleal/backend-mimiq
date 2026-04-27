from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

os.environ.setdefault("X_ADMIN_KEY", "bootstrap-test-key")

from core.config import Settings
from core.exceptions import GPUNotReadyError
from db.base import Base
from main import create_app
from models.gpu import GPUStatus, GPUStatusRead
from models.websocket import AcceptedMessage, CompletedMessage, StatusMessage
from models.voice import AudioHealthReport
from services import AppServices
from services.auth import AuthService
from services.generation_service import GenerationService
from services.tts_runtime_state import TTSRuntimeStateService
from services.voice_service import VoiceService


class FakeStorageService:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def upload_sample(self, content: bytes, content_type: str | None, filename: str | None) -> str:
        path = f"gs://samples/{uuid4()}.wav"
        self.objects[path] = content
        return path

    async def upload_output(self, generation_id: str, content: bytes) -> str:
        path = f"gs://outputs/generations/{generation_id}.wav"
        self.objects[path] = content
        return path

    async def download_bytes(self, gcs_path: str) -> bytes:
        return self.objects[gcs_path]

    async def delete(self, gcs_path: str) -> None:
        self.objects.pop(gcs_path, None)


class FakeAudioHealthAnalyzer:
    async def analyze_upload(self, upload) -> tuple[bytes, AudioHealthReport]:
        content = await upload.read()
        report = AudioHealthReport(
            passed=True,
            duration_seconds=61.0,
            average_db=-20.0,
            peak_db=-6.0,
            noise_floor_db=-55.0,
            estimated_snr_db=35.0,
            clipped_ratio=0.0,
            issues=[],
            recommendations=[],
        )
        return content, report


class FakeLLMPreprocessor:
    async def rewrite_text(self, text: str, style_prompt: str) -> str:
        return f"{style_prompt}: {text}"


class FakeGPUOrchestrator:
    def __init__(self):
        self.status = GPUStatus.OFFLINE
        self.endpoint: str | None = None
        self.instance_id: str | None = None
        self.detail = "No active GPU instance."
        self.startup_dispatches = 0

    async def get_status(self, session=None) -> GPUStatusRead:
        del session
        return GPUStatusRead(
            status=self.status,
            endpoint=self.endpoint,
            instance_id=self.instance_id,
            detail=self.detail,
        )

    async def ensure_boot_requested(self, session=None) -> GPUStatusRead:
        del session
        if self.status is GPUStatus.OFFLINE:
            self.status = GPUStatus.BOOTING
            self.detail = "Start workflow dispatched. Waiting for TTS service registration."
            self.startup_dispatches += 1
        return await self.get_status()

    async def get_streaming_endpoint(self, session=None) -> str:
        del session
        if self.status is not GPUStatus.READY or not self.endpoint:
            raise RuntimeError("TTS endpoint is not ready")
        return self.endpoint

    async def register_tts_endpoint(self, session, endpoint: str, instance_id: str | None) -> GPUStatusRead:
        del session
        self.status = GPUStatus.READY
        self.endpoint = endpoint
        self.instance_id = instance_id
        self.detail = "TTS service registered with backend."
        return await self.get_status()

    async def mark_offline(self, session, instance_id: str | None, reason: str | None) -> GPUStatusRead:
        del session
        self.status = GPUStatus.OFFLINE
        self.endpoint = None
        self.instance_id = instance_id
        self.detail = reason or "TTS service reported offline."
        return await self.get_status()


class FakeTTSProxyService:
    def __init__(self, gpu: FakeGPUOrchestrator):
        self.gpu = gpu

    async def proxy_generation(self, websocket, session, payload) -> None:
        del session
        status = await self.gpu.ensure_boot_requested()
        await websocket.send_json(StatusMessage(status=status.status, detail=status.detail).model_dump())
        if status.status is not GPUStatus.READY:
            raise GPUNotReadyError(status)

        await websocket.send_json(
            AcceptedMessage(generation_id="gen-test", rewritten_text=payload.original_text).model_dump()
        )
        await websocket.send_bytes(b"fake-stream-audio")
        await websocket.send_json(
            CompletedMessage(
                generation_id="gen-test",
                output_gcs_path="gs://outputs/generations/gen-test.wav",
            ).model_dump()
        )


def build_test_services(settings: Settings, http_client: AsyncClient) -> AppServices:
    del http_client
    storage = FakeStorageService()
    gpu = FakeGPUOrchestrator()
    return AppServices(
        auth=AuthService(settings),
        audio_health=FakeAudioHealthAnalyzer(),
        storage=storage,
        llm=FakeLLMPreprocessor(),
        gpu=gpu,
        tts_runtime_state=TTSRuntimeStateService(),
        voices=VoiceService(),
        generations=GenerationService(),
        tts_proxy=FakeTTSProxyService(gpu),
    )


async def initialize_database(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture
def client(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    settings = Settings(
        x_admin_key="test-admin-key",
        database_url=database_url,
        cookie_name="pvc_admin_session",
        cookie_secure=False,
        gcs_sample_bucket="samples",
        gcs_output_bucket="outputs",
        llm_api_url="https://llm.test/v1/rewrite",
        internal_secret="internal-test-secret",
    )
    asyncio.run(initialize_database(settings.resolved_database_url))
    app = create_app(settings=settings, services_factory=build_test_services)
    with TestClient(app) as test_client:
        yield test_client
