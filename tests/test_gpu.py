from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import Settings
from db.base import Base
from models.db import TTSRuntimeState
from models.gpu import GPUStatus
from services.gpu import GPUOrchestrator
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
    )


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
                    last_error="Start workflow dispatched. Waiting for TTS service registration.",
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
        assert status.detail == "TTS startup timed out waiting for registration."

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
                    last_error="Start workflow dispatched. Waiting for TTS service registration.",
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
        assert status.detail == "Start workflow dispatched. Waiting for TTS service registration."

    asyncio.run(run())
