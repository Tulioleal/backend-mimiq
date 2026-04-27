from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.db import TTSRuntimeState
from models.gpu import GPUStatus, GPUStatusRead


class TTSRuntimeStateService:
    CURRENT_ROW_ID = 1

    async def get_current_state(self, session: AsyncSession) -> TTSRuntimeState | None:
        return await session.get(TTSRuntimeState, self.CURRENT_ROW_ID)

    async def mark_booting(self, session: AsyncSession, detail: str | None = None) -> TTSRuntimeState:
        state = await self._get_or_create(session)
        state.status = GPUStatus.BOOTING.value
        state.last_error = detail
        state.updated_at = self._now()
        await session.commit()
        await session.refresh(state)
        return state

    async def mark_ready(
        self,
        session: AsyncSession,
        instance_id: str | None,
        endpoint: str,
    ) -> TTSRuntimeState:
        state = await self._get_or_create(session)
        state.status = GPUStatus.READY.value
        state.instance_id = instance_id
        state.endpoint = endpoint
        state.registered_at = self._now()
        state.last_error = None
        state.updated_at = self._now()
        await session.commit()
        await session.refresh(state)
        return state

    async def mark_offline(
        self,
        session: AsyncSession,
        instance_id: str | None,
        reason: str | None,
    ) -> TTSRuntimeState:
        state = await self._get_or_create(session)
        if instance_id and state.instance_id and instance_id != state.instance_id:
            return state
        state.status = GPUStatus.OFFLINE.value
        state.instance_id = instance_id
        state.endpoint = None
        state.last_error = reason
        state.updated_at = self._now()
        await session.commit()
        await session.refresh(state)
        return state

    async def set_state(
        self,
        session: AsyncSession,
        status: GPUStatus,
        *,
        instance_id: str | None,
        endpoint: str | None,
        detail: str | None,
        registered_at: datetime | None = None,
    ) -> TTSRuntimeState:
        state = await self._get_or_create(session)
        state.status = status.value
        state.instance_id = instance_id
        state.endpoint = endpoint
        state.last_error = detail
        state.registered_at = registered_at
        state.updated_at = self._now()
        await session.commit()
        await session.refresh(state)
        return state

    def to_read_model(self, state: TTSRuntimeState | None, detail_override: str | None = None) -> GPUStatusRead:
        if state is None:
            return GPUStatusRead(status=GPUStatus.OFFLINE, detail=detail_override or "No active GPU instance.")
        return GPUStatusRead(
            status=GPUStatus(state.status),
            instance_id=state.instance_id,
            endpoint=state.endpoint,
            detail=detail_override if detail_override is not None else state.last_error,
        )

    async def _get_or_create(self, session: AsyncSession) -> TTSRuntimeState:
        state = await self.get_current_state(session)
        if state is not None:
            return state
        state = TTSRuntimeState(id=self.CURRENT_ROW_ID, status=GPUStatus.OFFLINE.value)
        session.add(state)
        await session.commit()
        await session.refresh(state)
        return state

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
