from __future__ import annotations

from httpx import AsyncClient, HTTPStatusError

from core.config import Settings
from core.exceptions import ConfigurationError
from utils.get_ip import get_gce_external_ip


class GitHubActionsService:
    def __init__(self, settings: Settings, http_client: AsyncClient):
        self.settings = settings
        self.http_client = http_client

    @property
    def configured(self) -> bool:
        return all(
            [
                self.settings.github_token,
                self.settings.github_owner,
                self.settings.github_repo,
                self.settings.github_start_workflow,
            ]
        )

    async def dispatch_start_workflow(self) -> None:
        if not self.configured:
            raise ConfigurationError(
                "GitHub Actions startup is not configured. Set GITHUB_TOKEN, GITHUB_OWNER, "
                "GITHUB_REPO, and GITHUB_START_WORKFLOW."
            )
        
        backend_ip = self.settings.backend_public_ip or get_gce_external_ip()
        backend_url = self.settings.backend_url or f"http://{backend_ip}:8000"
        backend_ws_url = self.settings.backend_ws_url or f"ws://{backend_ip}:8000/internal/tts-worker/ws"

        payload: dict[str, object] = {
            "ref": self.settings.github_ref,
            "inputs": {
                **self.settings.github_start_workflow_inputs,
                "backend_url": backend_url,
                "backend_ws_url": backend_ws_url,
            }
        }

        response = await self.http_client.post(
            (
                f"{self.settings.github_api_url.rstrip('/')}/repos/"
                f"{self.settings.github_owner}/{self.settings.github_repo}/actions/workflows/"
                f"{self.settings.github_start_workflow}/dispatches"
            ),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.settings.github_token}",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            json=payload,
            timeout=30.0,
        )
        try:
            response.raise_for_status()
        except HTTPStatusError as exc:
            raise RuntimeError(
                f"GitHub workflow dispatch failed ({response.status_code}): {response.text}"
            ) from exc
