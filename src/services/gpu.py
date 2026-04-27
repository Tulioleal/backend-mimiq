from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from httpx import AsyncClient
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
    endpoint: str | None = None
    detail: str | None = None
    startup_requested_at: datetime | None = None
    last_start_error: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GPUOrchestrator:
    def __init__(
        self,
        settings: Settings,
        http_client: AsyncClient,
        runtime_state_service: TTSRuntimeStateService,
        github_actions: GitHubActionsService | None = None,
    ):
        self.settings = settings
        self.http_client = http_client
        self.runtime_state_service = runtime_state_service
        self.github_actions = github_actions
        self._state = RuntimeState(
            status=GPUStatus.READY if settings.tts_endpoint else GPUStatus.OFFLINE,
            endpoint=settings.tts_endpoint,
            detail="Static TTS endpoint configured." if settings.tts_endpoint else None,
        )
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

            if self.settings.tts_endpoint:
                self._state.status = GPUStatus.BOOTING
                self._state.detail = "Configured TTS endpoint is not healthy yet."
                self._state.updated_at = self._now()
                await self.runtime_state_service.set_state(
                    session,
                    GPUStatus.BOOTING,
                    instance_id=None,
                    endpoint=self.settings.tts_endpoint,
                    detail=self._state.detail,
                )
                return self._snapshot()

            if not self.github_actions:
                raise ConfigurationError(
                    "No TTS startup mechanism is configured. Set TTS_ENDPOINT or GitHub Actions settings."
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
            self._state.detail = "Start workflow dispatched. Waiting for TTS service registration."
            self._state.startup_requested_at = now
            self._state.last_start_error = None
            self._state.updated_at = now
            await self.runtime_state_service.mark_booting(session, self._state.detail)
            return self._snapshot()

    async def get_streaming_endpoint(self, session: AsyncSession) -> str:
        status = await self.get_status(session)
        if status.status is not GPUStatus.READY or not status.endpoint:
            raise RuntimeError("TTS endpoint is not ready")
        return status.endpoint

    async def register_tts_endpoint(
        self,
        session: AsyncSession,
        endpoint: str,
        instance_id: str | None,
    ) -> GPUStatusRead:
        async with self._lock:
            now = self._now()
            await self.runtime_state_service.mark_ready(session, instance_id, endpoint)
            self._state = RuntimeState(
                status=GPUStatus.READY,
                endpoint=endpoint,
                instance_id=instance_id,
                detail="TTS service registered with backend.",
                startup_requested_at=self._state.startup_requested_at or now,
                updated_at=now,
            )
            return self._snapshot()

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
        if self._state.endpoint and await self._healthcheck(self._state.endpoint):
            self._state.status = GPUStatus.READY
            self._state.detail = "TTS service passed health check."
            self._state.updated_at = now
            await self.runtime_state_service.set_state(
                session,
                GPUStatus.READY,
                instance_id=self._state.instance_id,
                endpoint=self._state.endpoint,
                detail=None,
                registered_at=now,
            )
            return

        if self.settings.tts_endpoint:
            self._state.status = GPUStatus.BOOTING
            self._state.endpoint = self.settings.tts_endpoint
            self._state.detail = "Configured TTS endpoint is not healthy yet."
            self._state.updated_at = now
            await self.runtime_state_service.set_state(
                session,
                GPUStatus.BOOTING,
                instance_id=None,
                endpoint=self.settings.tts_endpoint,
                detail=self._state.detail,
                registered_at=None,
            )
            return

        if self._state.startup_requested_at and not self._boot_timed_out(self._state.startup_requested_at, now):
            self._state.status = GPUStatus.BOOTING
            if self._state.endpoint:
                self._state.detail = "TTS endpoint registered, waiting for health check."
            else:
                self._state.detail = "Start workflow dispatched. Waiting for TTS service registration."
            self._state.updated_at = now
            await self.runtime_state_service.set_state(
                session,
                GPUStatus.BOOTING,
                instance_id=self._state.instance_id,
                endpoint=self._state.endpoint,
                detail=self._state.detail,
                registered_at=self._state.startup_requested_at,
            )
            return

        self._state.status = GPUStatus.OFFLINE
        if self._state.endpoint:
            self._state.detail = "Registered TTS endpoint is unhealthy."
        elif self._state.startup_requested_at:
            self._state.detail = "TTS startup timed out waiting for registration."
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

    async def _healthcheck(self, endpoint: str) -> bool:
        health_url = endpoint.rstrip("/") + self.settings.tts_health_path
        try:
            response = await self.http_client.get(health_url, timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def _boot_timed_out(self, startup_requested_at: datetime, now: datetime) -> bool:
        elapsed = (now - startup_requested_at).total_seconds()
        return elapsed >= self.settings.tts_boot_timeout_seconds

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _hydrate_from_persisted_state(self, persisted_state: TTSRuntimeState | None) -> None:
        if persisted_state is None:
            self._state.status = GPUStatus.READY if self.settings.tts_endpoint else GPUStatus.OFFLINE
            self._state.instance_id = None
            self._state.endpoint = self.settings.tts_endpoint
            self._state.detail = "Static TTS endpoint configured." if self.settings.tts_endpoint else None
            self._state.startup_requested_at = None
            self._state.last_start_error = None
            return

        self._state.status = GPUStatus(persisted_state.status)
        self._state.instance_id = persisted_state.instance_id
        self._state.endpoint = persisted_state.endpoint
        self._state.startup_requested_at = (
            persisted_state.updated_at
            if persisted_state.status == GPUStatus.BOOTING.value
            else persisted_state.registered_at
        )
        self._state.last_start_error = persisted_state.last_error
        self._state.detail = None if persisted_state.status == GPUStatus.READY.value else persisted_state.last_error

    def _snapshot(self) -> GPUStatusRead:
        return GPUStatusRead(
            status=self._state.status,
            instance_id=self._state.instance_id,
            endpoint=self._state.endpoint,
            detail=self._state.detail,
        )
