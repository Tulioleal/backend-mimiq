from __future__ import annotations

import asyncio

import httpx
import pytest

from core.config import Settings
from core.exceptions import ConfigurationError
from services.runpod import RunPodService


def build_settings(**overrides) -> Settings:
    values = {
        "x_admin_key": "test-admin-key",
        "database_url": "sqlite+aiosqlite:///test.db",
        "gcs_sample_bucket": "samples",
        "gcs_output_bucket": "outputs",
        "llm_api_url": "https://llm.test/v1/rewrite",
        "internal_secret": "internal-test-secret",
        "backend_url": "https://backend.test",
        "backend_ws_url": "wss://backend.test/internal/tts-worker/ws",
        "runpod_api_key": "runpod-test-key",
        "runpod_image_name": "repo/pvc-tts:latest",
        "runpod_start_retry_seconds": 1,
    }
    values.update(overrides)
    return Settings(**values)

class FakeHTTPClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return self.responses.pop(0)

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return self.responses.pop(0)

    async def delete(self, url, **kwargs):
        self.requests.append(("DELETE", url, kwargs))
        return self.responses.pop(0)


def response(status_code: int, json_body) -> httpx.Response:
    request = httpx.Request("POST", "https://rest.runpod.io/v1/pods")
    return httpx.Response(status_code, json=json_body, request=request)


def test_create_pod_sends_auth_header_and_provider_neutral_payload() -> None:
    async def run() -> None:
        client = FakeHTTPClient([response(200, {"id": "pod-123", "status": "RUNNING"})])
        service = RunPodService(build_settings(), client)

        pod = await service.create_pod("worker-123")

        method, url, kwargs = client.requests[0]
        payload = kwargs["json"]
        assert pod["id"] == "pod-123"
        assert method == "POST"
        assert url == "https://rest.runpod.io/v1/pods"
        assert kwargs["headers"] == {"Authorization": "Bearer runpod-test-key"}
        assert payload["imageName"] == "repo/pvc-tts:latest"
        assert payload["gpuTypeIds"] == [
            "NVIDIA GeForce RTX 4090",
            "NVIDIA GeForce RTX 3090",
            "NVIDIA RTX A5000",
            "NVIDIA A40",
        ]
        assert payload["gpuTypePriority"] == "availability"
        assert payload["minRAMPerGPU"] == 16
        assert payload["minVCPUPerGPU"] == 4
        assert payload["ports"] == ["8000/http"]
        assert payload["env"] == {
            "BACKEND_URL": "https://backend.test",
            "BACKEND_WS_URL": "wss://backend.test/internal/tts-worker/ws",
            "INTERNAL_SECRET": "internal-test-secret",
            "TTS_PROVIDER": "generic",
            "TTS_INSTANCE_ID": "worker-123",
            "WATCHDOG_TIMEOUT_SECONDS": "0",
        }
        assert "RUNPOD_API_KEY" not in payload["env"]

    asyncio.run(run())


def test_create_pod_uses_backend_public_url_fallback() -> None:
    async def run() -> None:
        client = FakeHTTPClient([response(200, {"id": "pod-123", "status": "RUNNING"})])
        service = RunPodService(
            build_settings(backend_url=None, backend_public_url="https://public-backend.test"),
            client,
        )

        await service.create_pod("worker-123")

        payload = client.requests[0][2]["json"]
        assert payload["env"]["BACKEND_URL"] == "https://public-backend.test"

    asyncio.run(run())


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"backend_url": None, "backend_public_url": None}, "BACKEND_URL"),
        ({"backend_ws_url": None}, "BACKEND_WS_URL"),
        ({"internal_secret": None}, "INTERNAL_SECRET"),
    ],
)
def test_worker_env_validation_requires_callback_settings(overrides, missing) -> None:
    async def run() -> None:
        client = FakeHTTPClient([])
        service = RunPodService(build_settings(**overrides), client)

        with pytest.raises(ConfigurationError, match=missing):
            await service.ensure_worker_pod_started(worker_instance_id="worker-123")

        assert client.requests == []

    asyncio.run(run())


def test_worker_env_validation_rejects_local_callback_hosts() -> None:
    async def run() -> None:
        client = FakeHTTPClient([])
        service = RunPodService(
            build_settings(
                backend_url="http://127.0.0.1:8000",
                backend_ws_url="ws://localhost:8000/internal/tts-worker/ws",
            ),
            client,
        )

        with pytest.raises(ConfigurationError, match="reachable from RunPod/public internet"):
            await service.ensure_worker_pod_started(worker_instance_id="worker-123")

        assert client.requests == []

    asyncio.run(run())


def test_create_pod_retries_transient_availability_errors(monkeypatch) -> None:
    async def run() -> None:
        sleep_calls = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        monkeypatch.setattr("services.runpod.asyncio.sleep", fake_sleep)
        client = FakeHTTPClient(
            [
                response(200, []),
                response(409, {"error": "No GPU availability"}),
                response(200, {"id": "pod-123", "status": "RUNNING"}),
            ]
        )
        service = RunPodService(build_settings(), client)

        pod = await service.ensure_worker_pod_started(worker_instance_id="worker-123")

        assert pod.pod_id == "pod-123"
        assert [request[0] for request in client.requests] == ["GET", "POST", "POST"]
        assert sleep_calls

    asyncio.run(run())


def test_create_pod_does_not_retry_bad_request_schema_errors(monkeypatch) -> None:
    async def run() -> None:
        sleep_calls = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        monkeypatch.setattr("services.runpod.asyncio.sleep", fake_sleep)
        client = FakeHTTPClient(
            [
                response(200, []),
                response(
                    400,
                    {
                        "error": "The request body does not meet schema requirements",
                        "problems": ["value must be one of the available GPU types"],
                    },
                ),
            ]
        )
        service = RunPodService(build_settings(), client)

        with pytest.raises(RuntimeError, match="RunPod API request failed \\(400\\)"):
            await service.ensure_worker_pod_started(worker_instance_id="worker-123")

        assert [request[0] for request in client.requests] == ["GET", "POST"]
        assert sleep_calls == []

    asyncio.run(run())


def test_existing_running_pod_is_reused() -> None:
    async def run() -> None:
        client = FakeHTTPClient([response(200, [{"id": "pod-123", "name": "pvc-xtts", "status": "RUNNING"}])])
        service = RunPodService(build_settings(), client)

        pod = await service.ensure_worker_pod_started(worker_instance_id="worker-123")

        assert pod.pod_id == "pod-123"
        assert [request[0] for request in client.requests] == ["GET"]

    asyncio.run(run())
