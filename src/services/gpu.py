from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.exceptions import ConfigurationError
from models.db import TTSRuntimeState
from models.gpu import GPUStatus, GPUStatusRead
from services.github_actions import GitHubActionsService
from services.tts_runtime_state import TTSRuntimeStateService


@dataclass(slots=True)
class RuntimeState:
    status: GPUStatus = GPUStatus.OFFLINE
    instance_id: str | None = None
    detail: str | None = None
    startup_requested_at: datetime | None = None
    last_start_error: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GPUOrchestrator:
    def __init__(
        self,
        settings: Settings,
        http_client,
        runtime_state_service: TTSRuntimeStateService,
        github_actions: GitHubActionsService | None = None,
    ):
        self.settings = settings
        self.runtime_state_service = runtime_state_service
        self.github_actions = github_actions
        self._state = RuntimeState()
        self._worker_connected = False
        self._lock = asyncio.Lock()

    async def get_status(self, session: AsyncSession) -> GPUStatusRead:
        async with self._lock:
            await self._refresh_state_locked(session)
            return self._snapshot()

    async def ensure_boot_requested(self, session: AsyncSession) -> GPUStatusRead:
        async with self._lock:
            await self._refresh_state_locked(session)
            if self._state.status is not GPUStatus.OFFLINE:
                return self._snapshot()

            if not self.github_actions:
                raise ConfigurationError(
                    "No TTS startup mechanism is configured. Set GitHub Actions settings."
                )

            try:
                await self.github_actions.dispatch_start_workflow()
            except Exception as exc:
                self._state.status = GPUStatus.OFFLINE
                self._state.detail = str(exc)
                self._state.last_start_error = str(exc)
                self._state.startup_requested_at = None
                self._state.updated_at = self._now()
                raise

            now = self._now()
            self._state.status = GPUStatus.BOOTING
            self._state.detail = "Start workflow dispatched. Waiting for TTS worker connection."
            self._state.startup_requested_at = now
            self._state.last_start_error = None
            self._state.updated_at = now
            await self.runtime_state_service.mark_booting(session, self._state.detail)
            return self._snapshot()

    async def mark_worker_connected(
        self,
        session: AsyncSession,
        instance_id: str | None,
    ) -> GPUStatusRead:
        async with self._lock:
            now = self._now()
            await self.runtime_state_service.set_state(
                session,
                GPUStatus.READY,
                instance_id=instance_id,
                endpoint=None,
                detail=None,
                registered_at=now,
            )
            self._worker_connected = True
            self._state = RuntimeState(
                status=GPUStatus.READY,
                instance_id=instance_id,
                detail="TTS worker connected.",
                startup_requested_at=self._state.startup_requested_at or now,
                updated_at=now,
            )
            return self._snapshot()

    async def mark_worker_disconnected(
        self,
        session: AsyncSession,
        instance_id: str | None,
        reason: str | None,
    ) -> GPUStatusRead:
        return await self.mark_offline(session, instance_id, reason or "TTS worker disconnected.")

    async def mark_offline(
        self,
        session: AsyncSession,
        instance_id: str | None,
        reason: str | None,
    ) -> GPUStatusRead:
        async with self._lock:
            if instance_id and self._state.instance_id and instance_id != self._state.instance_id:
                return self._snapshot()
            await self.runtime_state_service.mark_offline(session, instance_id, reason)
            self._worker_connected = False
            self._state = RuntimeState(
                status=GPUStatus.OFFLINE,
                detail=reason or "TTS service reported offline.",
                last_start_error=reason,
            )
            return self._snapshot()

    async def _refresh_state_locked(self, session: AsyncSession) -> None:
        persisted_state = await self.runtime_state_service.get_current_state(session)
        self._hydrate_from_persisted_state(persisted_state)
        now = self._now()
        if self._state.status is GPUStatus.READY:
            return

        if self._state.startup_requested_at and not self._boot_timed_out(self._state.startup_requested_at, now):
            self._state.status = GPUStatus.BOOTING
            self._state.detail = "Start workflow dispatched. Waiting for TTS worker connection."
            self._state.updated_at = now
            await self.runtime_state_service.set_state(
                session,
                GPUStatus.BOOTING,
                instance_id=self._state.instance_id,
                endpoint=None,
                detail=self._state.detail,
                registered_at=self._state.startup_requested_at,
            )
            return

        was_booting = self._state.status is GPUStatus.BOOTING
        self._state.status = GPUStatus.OFFLINE
        if self._state.startup_requested_at or was_booting:
            self._state.detail = "TTS startup timed out waiting for worker connection."
        else:
            self._state.detail = self._state.last_start_error or "No active GPU instance."
        self._state.updated_at = now
        await self.runtime_state_service.set_state(
            session,
            GPUStatus.OFFLINE,
            instance_id=self._state.instance_id,
            endpoint=None,
            detail=self._state.detail,
            registered_at=self._state.startup_requested_at,
        )

    def _boot_timed_out(self, startup_requested_at: datetime, now: datetime) -> bool:
        if startup_requested_at.tzinfo is None:
            startup_requested_at = startup_requested_at.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        elapsed = (now - startup_requested_at).total_seconds()
        return elapsed >= self.settings.tts_boot_timeout_seconds

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _hydrate_from_persisted_state(self, persisted_state: TTSRuntimeState | None) -> None:
        if persisted_state is None:
            self._state.status = GPUStatus.OFFLINE
            self._state.instance_id = None
            self._state.detail = None
            self._state.startup_requested_at = None
            self._state.last_start_error = None
            return

        self._state.status = GPUStatus(persisted_state.status)
        self._state.instance_id = persisted_state.instance_id
        self._state.startup_requested_at = persisted_state.registered_at
        self._state.last_start_error = persisted_state.last_error
        self._state.detail = (
            None if persisted_state.status == GPUStatus.READY.value else persisted_state.last_error
        )
        if self._state.status is GPUStatus.READY and not self._worker_connected:
            self._state.status = GPUStatus.OFFLINE
            self._state.detail = "No active TTS worker."

    def _snapshot(self) -> GPUStatusRead:
        return GPUStatusRead(
            status=self._state.status,
            instance_id=self._state.instance_id,
            endpoint=None,
            detail=self._state.detail,
        )
