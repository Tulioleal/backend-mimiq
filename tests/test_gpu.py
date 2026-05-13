from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import Settings
from db.base import Base
from models.db import TTSRuntimeState
from models.gpu import GPUStatus
from services.gpu import GPUOrchestrator
from services.runpod import RunPodWorkerPod
from services.tts_runtime_state import TTSRuntimeStateService


async def setup_sessionmaker(database_url: str) -> async_sessionmaker:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def build_settings(database_url: str) -> Settings:
    return Settings(
        x_admin_key="test-admin-key",
        database_url=database_url,
        cookie_name="pvc_admin_session",
        cookie_secure=False,
        gcs_sample_bucket="samples",
        gcs_output_bucket="outputs",
        llm_api_url="https://llm.test/v1/rewrite",
        internal_secret="internal-test-secret",
        tts_boot_timeout_seconds=600,
        backend_url="https://backend.test",
        backend_ws_url="wss://backend.test/internal/tts-worker/ws",
        runpod_api_key="runpod-test-key",
        runpod_image_name="repo/pvc-tts:latest",
        tts_idle_timeout_seconds=1800,
    )


class FakeRunPodService:
    def __init__(self):
        self.started = []
        self.shutdowns = []

    async def ensure_worker_pod_started(self, *, worker_instance_id, provider_instance_id=None):
        self.started.append((worker_instance_id, provider_instance_id))
        return RunPodWorkerPod("pod-123", worker_instance_id, {"id": "pod-123"})

    async def shutdown_pod(self, pod_id: str) -> None:
        self.shutdowns.append(pod_id)


def test_booting_status_times_out_from_original_start_time(tmp_path) -> None:
    async def run() -> None:
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'gpu.db'}"
        session_maker = await setup_sessionmaker(database_url)
        now = datetime.now(timezone.utc)

        async with session_maker() as session:
            session.add(
                TTSRuntimeState(
                    id=TTSRuntimeStateService.CURRENT_ROW_ID,
                    status=GPUStatus.BOOTING.value,
                    registered_at=now - timedelta(seconds=601),
                    updated_at=now,
                    last_error="Start workflow dispatched. Waiting for TTS worker connection.",
                )
            )
            await session.commit()

        gpu = GPUOrchestrator(
            build_settings(database_url),
            http_client=None,
            runtime_state_service=TTSRuntimeStateService(),
        )
        async with session_maker() as session:
            status = await gpu.get_status(session)

        assert status.status == GPUStatus.OFFLINE
        assert status.detail == "TTS startup timed out waiting for worker connection."

    asyncio.run(run())


def test_booting_status_stays_booting_before_timeout(tmp_path) -> None:
    async def run() -> None:
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'gpu.db'}"
        session_maker = await setup_sessionmaker(database_url)
        now = datetime.now(timezone.utc)

        async with session_maker() as session:
            session.add(
                TTSRuntimeState(
                    id=TTSRuntimeStateService.CURRENT_ROW_ID,
                    status=GPUStatus.BOOTING.value,
                    registered_at=now - timedelta(seconds=30),
                    updated_at=now,
                    last_error="Start workflow dispatched. Waiting for TTS worker connection.",
                )
            )
            await session.commit()

        gpu = GPUOrchestrator(
            build_settings(database_url),
            http_client=None,
            runtime_state_service=TTSRuntimeStateService(),
        )
        async with session_maker() as session:
            status = await gpu.get_status(session)

        assert status.status == GPUStatus.BOOTING
        assert status.detail == "RunPod pod started. Waiting for TTS worker connection."

    asyncio.run(run())


def test_runpod_boot_sets_worker_and_provider_ids(tmp_path) -> None:
    async def run() -> None:
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'gpu.db'}"
        session_maker = await setup_sessionmaker(database_url)
        runpod = FakeRunPodService()
        gpu = GPUOrchestrator(
            build_settings(database_url),
            http_client=None,
            runtime_state_service=TTSRuntimeStateService(),
            runpod=runpod,
        )

        async with session_maker() as session:
            status = await gpu.ensure_boot_requested(session)
            state = await session.get(TTSRuntimeState, TTSRuntimeStateService.CURRENT_ROW_ID)

        assert status.status == GPUStatus.BOOTING
        assert status.instance_id.startswith("runpod-")
        assert state.provider_instance_id == "pod-123"
        assert runpod.started[0] == (status.instance_id, None)

    asyncio.run(run())


def test_idle_timeout_deletes_runpod_pod(tmp_path) -> None:
    async def run() -> None:
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'gpu.db'}"
        session_maker = await setup_sessionmaker(database_url)
        settings = build_settings(database_url).model_copy(update={"tts_idle_timeout_seconds": 0})
        runpod = FakeRunPodService()
        gpu = GPUOrchestrator(
            settings,
            http_client=None,
            runtime_state_service=TTSRuntimeStateService(),
            runpod=runpod,
        )
        gpu.set_session_maker(session_maker)

        async with session_maker() as session:
            booting = await gpu.ensure_boot_requested(session)
            await gpu.mark_worker_connected(session, booting.instance_id)

        await asyncio.sleep(0.01)

        async with session_maker() as session:
            status = await gpu.get_status(session)

        assert runpod.shutdowns == ["pod-123"]
        assert status.status == GPUStatus.OFFLINE

    asyncio.run(run())
