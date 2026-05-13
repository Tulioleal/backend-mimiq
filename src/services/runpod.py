from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from httpx import AsyncClient, HTTPStatusError, Response

from core.config import Settings
from core.exceptions import ConfigurationError


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunPodWorkerPod:
    pod_id: str
    worker_instance_id: str
    pod: dict[str, object]


class RunPodService:
    def __init__(self, settings: Settings, http_client: AsyncClient):
        self.settings = settings
        self.http_client = http_client

    @property
    def configured(self) -> bool:
        return bool(self.settings.runpod_api_key and self.settings.runpod_image_name)

    async def create_pod(self, worker_instance_id: str) -> dict[str, object]:
        payload = self._create_pod_payload(worker_instance_id)
        response = await self.http_client.post(
            f"{self._base_url}/pods",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        try:
            self._raise_for_status(response)
        except RuntimeError:
            logger.error("RunPod pod create failed with payload: %s", self._sanitized_create_pod_payload(payload))
            raise
        return response.json()

    async def get_pod(self, pod_id: str) -> dict[str, object]:
        response = await self.http_client.get(
            f"{self._base_url}/pods/{pod_id}",
            headers=self._headers,
            timeout=30.0,
        )
        self._raise_for_status(response)
        return response.json()

    async def list_pods(self) -> list[dict[str, object]]:
        response = await self.http_client.get(
            f"{self._base_url}/pods",
            headers=self._headers,
            timeout=30.0,
        )
        self._raise_for_status(response)
        body = response.json()
        if isinstance(body, list):
            return body
        pods = body.get("pods") if isinstance(body, dict) else None
        return pods if isinstance(pods, list) else []

    async def delete_pod(self, pod_id: str) -> None:
        response = await self.http_client.delete(
            f"{self._base_url}/pods/{pod_id}",
            headers=self._headers,
            timeout=30.0,
        )
        self._raise_for_status(response)

    async def shutdown_pod(self, pod_id: str) -> None:
        if self.settings.runpod_shutdown_action.lower() == "delete":
            await self.delete_pod(pod_id)
            return
        response = await self.http_client.post(
            f"{self._base_url}/pods/{pod_id}/stop",
            headers=self._headers,
            timeout=30.0,
        )
        self._raise_for_status(response)

    async def ensure_worker_pod_started(
        self,
        *,
        worker_instance_id: str,
        provider_instance_id: str | None = None,
    ) -> RunPodWorkerPod:
        if not self.configured:
            raise ConfigurationError("RunPod is not configured. Set RUNPOD_API_KEY and RUNPOD_IMAGE_NAME.")
        self._validate_worker_env()

        if provider_instance_id:
            pod = await self.get_pod(provider_instance_id)
            if not self._pod_is_terminated(pod):
                return RunPodWorkerPod(provider_instance_id, worker_instance_id, pod)

        existing = await self._find_existing_worker_pod()
        if existing is not None:
            pod_id = str(existing["id"])
            return RunPodWorkerPod(pod_id, worker_instance_id, existing)

        deadline = time.monotonic() + max(self.settings.runpod_start_retry_seconds, 0)
        while True:
            try:
                pod = await self.create_pod(worker_instance_id)
                pod_id = str(pod["id"])
                return RunPodWorkerPod(pod_id, worker_instance_id, pod)
            except Exception as exc:
                if not self._is_retryable_create_error(exc) or time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(min(5.0, max(deadline - time.monotonic(), 0.0)))

    async def _find_existing_worker_pod(self) -> dict[str, object] | None:
        for pod in await self.list_pods():
            if pod.get("name") == self.settings.runpod_pod_name and not self._pod_is_terminated(pod):
                return pod
        return None

    def _create_pod_payload(self, worker_instance_id: str) -> dict[str, object]:
        if not self.settings.runpod_image_name:
            raise ConfigurationError("RUNPOD_IMAGE_NAME must be set to create a RunPod pod.")
        return {
            "name": self.settings.runpod_pod_name,
            "imageName": self.settings.runpod_image_name,
            "gpuTypeIds": self.settings.runpod_gpu_type_ids,
            "gpuTypePriority": self.settings.runpod_gpu_type_priority,
            "minRAMPerGPU": self.settings.runpod_min_ram_per_gpu,
            "minVCPUPerGPU": self.settings.runpod_min_vcpu_per_gpu,
            "volumeInGb": self.settings.runpod_volume_gb,
            "containerDiskInGb": self.settings.runpod_container_disk_gb,
            "ports": self.settings.runpod_ports,
            "interruptible": self.settings.runpod_interruptible,
            "supportPublicIp": True,
            "env": {
                "BACKEND_URL": self._backend_url,
                "BACKEND_WS_URL": self.settings.backend_ws_url,
                "INTERNAL_SECRET": self.settings.internal_secret,
                "TTS_PROVIDER": "generic",
                "TTS_INSTANCE_ID": worker_instance_id,
                "WATCHDOG_TIMEOUT_SECONDS": "0",
            },
        }

    def _validate_worker_env(self) -> None:
        missing = []
        if not self._backend_url:
            missing.append("BACKEND_URL")
        if not self.settings.backend_ws_url:
            missing.append("BACKEND_WS_URL")
        if not self.settings.internal_secret:
            missing.append("INTERNAL_SECRET")
        if missing:
            raise ConfigurationError(
                "Missing RunPod worker environment settings: "
                f"{', '.join(missing)}. BACKEND_URL and BACKEND_WS_URL must be reachable from RunPod."
            )

        local_urls = []
        if self._uses_local_callback_host(self._backend_url):
            local_urls.append("BACKEND_URL")
        if self._uses_local_callback_host(self.settings.backend_ws_url):
            local_urls.append("BACKEND_WS_URL")
        if local_urls:
            raise ConfigurationError(
                "RunPod worker callback URLs must be reachable from RunPod/public internet; "
                f"do not use localhost or private network hosts for: {', '.join(local_urls)}"
            )

    def _raise_for_status(self, response: Response) -> None:
        try:
            response.raise_for_status()
        except HTTPStatusError as exc:
            raise RuntimeError(f"RunPod API request failed ({response.status_code}): {response.text}") from exc

    def _is_retryable_create_error(self, exc: Exception) -> bool:
        if not isinstance(exc, RuntimeError):
            return False
        message = str(exc).lower()
        if "runpod api request failed (400)" in message:
            return False
        return any(
            value in message
            for value in ["409", "429", "500", "502", "503", "504", "availability", "available"]
        )

    def _sanitized_create_pod_payload(self, payload: dict[str, object]) -> dict[str, object]:
        return {key: value for key, value in payload.items() if key != "env"}

    def _uses_local_callback_host(self, value: str | None) -> bool:
        if not value:
            return False
        host = urlparse(value).hostname
        if not host:
            return False
        if host == "localhost" or host.endswith(".localhost"):
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return address.is_private or address.is_loopback or address.is_link_local

    def _pod_is_terminated(self, pod: dict[str, object]) -> bool:
        status = str(pod.get("status") or pod.get("desiredStatus") or "").upper()
        return status in {"TERMINATED", "DELETED"}

    @property
    def _base_url(self) -> str:
        return self.settings.runpod_api_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.runpod_api_key}"}

    @property
    def _backend_url(self) -> str | None:
        return self.settings.backend_url or self.settings.backend_public_url
