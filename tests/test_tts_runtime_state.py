from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.base import Base
from models.gpu import GPUStatus
from services.tts_runtime_state import TTSRuntimeStateService


async def setup_sessionmaker(database_url: str) -> async_sessionmaker:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def test_runtime_state_service_persists_current_runtime(tmp_path) -> None:
    async def run() -> None:
        session_maker = await setup_sessionmaker(f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")
        service = TTSRuntimeStateService()

        async with session_maker() as session:
            booting = await service.mark_booting(session, "waiting for registration")
            assert booting.status == GPUStatus.BOOTING.value

        async with session_maker() as session:
            ready = await service.mark_ready(session, "vast-123", "http://tts.test:8000")
            assert ready.status == GPUStatus.READY.value
            assert ready.endpoint == "http://tts.test:8000"

        async with session_maker() as session:
            current = await service.get_current_state(session)
            assert current is not None
            assert current.instance_id == "vast-123"
            assert current.endpoint == "http://tts.test:8000"
            assert current.status == GPUStatus.READY.value

        async with session_maker() as session:
            offline = await service.mark_offline(session, "vast-123", "watchdog_timeout")
            assert offline.status == GPUStatus.OFFLINE.value
            assert offline.endpoint is None
            assert offline.last_error == "watchdog_timeout"

    asyncio.run(run())
