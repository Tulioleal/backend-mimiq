from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Settings
from core.exceptions import ConfigurationError
from models.db import TTSRuntimeState
from models.gpu import GPUStatus, GPUStatusRead
from services.github_actions import GitHubActionsService
from services.runpod import RunPodService
from services.tts_runtime_state import TTSRuntimeStateService


@dataclass(slots=True)
class RuntimeState:
    status: GPUStatus = GPUStatus.OFFLINE
    instance_id: str | None = None
    provider_instance_id: str | None = None
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
        runpod: RunPodService | None = None,
    ):
        del http_client
        self.settings = settings
        self.runtime_state_service = runtime_state_service
        self.github_actions = github_actions
        self.runpod = runpod
        self._state = RuntimeState()
        self._worker_connected = False
        self._lock = asyncio.Lock()
        self._session_maker: async_sessionmaker[AsyncSession] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._worker_busy = False

    def set_session_maker(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self._session_maker = session_maker

    async def get_status(self, session: AsyncSession) -> GPUStatusRead:
        async with self._lock:
            await self._refresh_state_locked(session)
            return self._snapshot()

    async def ensure_boot_requested(self, session: AsyncSession) -> GPUStatusRead:
        async with self._lock:
            await self._refresh_state_locked(session)
            if self._state.status is not GPUStatus.OFFLINE:
                return self._snapshot()

            try:
                detail = await self._request_start_locked()
            except Exception as exc:
                self._state.status = GPUStatus.OFFLINE
                self._state.detail = str(exc)
                self._state.last_start_error = str(exc)
                self._state.startup_requested_at = None
                self._state.updated_at = self._now()
                raise

            now = self._now()
            self._state.status = GPUStatus.BOOTING
            self._state.detail = detail
            self._state.startup_requested_at = now
            self._state.last_start_error = None
            self._state.updated_at = now
            await self.runtime_state_service.set_state(
                session,
                GPUStatus.BOOTING,
                instance_id=self._state.instance_id,
                provider_instance_id=self._state.provider_instance_id,
                endpoint=None,
                detail=self._state.detail,
                registered_at=now,
            )
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
                provider_instance_id=self._state.provider_instance_id,
                endpoint=None,
                detail=None,
                registered_at=now,
            )
            self._worker_connected = True
            self._worker_busy = False
            self._state = RuntimeState(
                status=GPUStatus.READY,
                instance_id=instance_id,
                provider_instance_id=self._state.provider_instance_id,
                detail="TTS worker connected.",
                startup_requested_at=self._state.startup_requested_at or now,
                updated_at=now,
            )
            self._schedule_idle_shutdown_locked()
            return self._snapshot()

    async def mark_worker_busy(self) -> None:
        async with self._lock:
            self._worker_busy = True
            self._cancel_idle_shutdown_locked()

    async def mark_worker_idle(self) -> None:
        async with self._lock:
            self._worker_busy = False
            self._schedule_idle_shutdown_locked()

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
            await self.runtime_state_service.set_state(
                session,
                GPUStatus.OFFLINE,
                instance_id=instance_id,
                provider_instance_id=None,
                endpoint=None,
                detail=reason,
                registered_at=None,
            )
            self._worker_connected = False
            self._worker_busy = False
            self._cancel_idle_shutdown_locked()
            self._state = RuntimeState(
                status=GPUStatus.OFFLINE,
                detail=reason or "TTS service reported offline.",
                last_start_error=reason,
            )
            return self._snapshot()

    async def _request_start_locked(self) -> str:
        if self.settings.tts_provider == "runpod":
            if not self.runpod:
                raise ConfigurationError("RunPod startup is not configured.")
            worker_instance_id = f"runpod-{uuid4()}"
            pod = await self.runpod.ensure_worker_pod_started(
                worker_instance_id=worker_instance_id,
                provider_instance_id=self._state.provider_instance_id,
            )
            self._state.instance_id = pod.worker_instance_id
            self._state.provider_instance_id = pod.pod_id
            return "RunPod pod started. Waiting for TTS worker connection."

        if not self.github_actions:
            raise ConfigurationError("No TTS startup mechanism is configured. Set GitHub Actions settings.")
        await self.github_actions.dispatch_start_workflow()
        return "Start workflow dispatched. Waiting for TTS worker connection."

    async def _refresh_state_locked(self, session: AsyncSession) -> None:
        persisted_state = await self.runtime_state_service.get_current_state(session)
        self._hydrate_from_persisted_state(persisted_state)
        now = self._now()
        if self._state.status is GPUStatus.READY:
            return

        if self._state.startup_requested_at and not self._boot_timed_out(self._state.startup_requested_at, now):
            self._state.status = GPUStatus.BOOTING
            if self.settings.tts_provider == "runpod":
                self._state.detail = "RunPod pod started. Waiting for TTS worker connection."
            else:
                self._state.detail = "Start workflow dispatched. Waiting for TTS worker connection."
            self._state.updated_at = now
            await self.runtime_state_service.set_state(
                session,
                GPUStatus.BOOTING,
                instance_id=self._state.instance_id,
                provider_instance_id=self._state.provider_instance_id,
                endpoint=None,
                detail=self._state.detail,
                registered_at=self._state.startup_requested_at,
            )
            return

        was_booting = self._state.status is GPUStatus.BOOTING
        self._state.status = GPUStatus.OFFLINE
        self._state.provider_instance_id = None
        if self._state.startup_requested_at or was_booting:
            self._state.detail = "TTS startup timed out waiting for worker connection."
        else:
            self._state.detail = self._state.last_start_error or "No active GPU instance."
        self._state.updated_at = now
        await self.runtime_state_service.set_state(
            session,
            GPUStatus.OFFLINE,
            instance_id=self._state.instance_id,
            provider_instance_id=None,
            endpoint=None,
            detail=self._state.detail,
            registered_at=self._state.startup_requested_at,
        )

    def _schedule_idle_shutdown_locked(self) -> None:
        if self.settings.tts_provider != "runpod" or self._worker_busy:
            return
        if self._state.status is not GPUStatus.READY or not self._state.provider_instance_id:
            return
        if self._session_maker is None or self.runpod is None:
            return
        self._cancel_idle_shutdown_locked()
        pod_id = self._state.provider_instance_id
        instance_id = self._state.instance_id
        self._idle_task = asyncio.create_task(self._idle_shutdown_after_timeout(pod_id, instance_id))

    def _cancel_idle_shutdown_locked(self) -> None:
        current_task = asyncio.current_task()
        if (
            self._idle_task is not None
            and not self._idle_task.done()
            and self._idle_task is not current_task
        ):
            self._idle_task.cancel()
        self._idle_task = None

    async def _idle_shutdown_after_timeout(self, pod_id: str, instance_id: str | None) -> None:
        try:
            await asyncio.sleep(self.settings.tts_idle_timeout_seconds)
            async with self._lock:
                if self._worker_busy or self._state.provider_instance_id != pod_id:
                    return
            if self.runpod is None or self._session_maker is None:
                return
            await self.runpod.shutdown_pod(pod_id)
            async with self._session_maker() as session:
                await self.mark_offline(session, instance_id, "TTS worker idle timeout.")
        except asyncio.CancelledError:
            raise

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
            self._state.provider_instance_id = None
            self._state.detail = None
            self._state.startup_requested_at = None
            self._state.last_start_error = None
            return

        self._state.status = GPUStatus(persisted_state.status)
        self._state.instance_id = persisted_state.instance_id
        self._state.provider_instance_id = persisted_state.provider_instance_id
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
