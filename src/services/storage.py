from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from google.cloud import storage

from core.config import Settings
from utils.audio import guess_audio_extension


class StorageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: storage.Client | None = None

    async def upload_sample(
        self,
        content: bytes,
        content_type: str | None,
        filename: str | None,
    ) -> str:
        extension = guess_audio_extension(filename, content_type)
        object_name = f"voices/{uuid.uuid4()}{extension}"
        return await self.upload_bytes(
            self.settings.gcs_sample_bucket,
            object_name,
            content,
            content_type or "application/octet-stream",
        )

    async def upload_output(self, generation_id: str, content: bytes) -> str:
        object_name = f"generations/{generation_id}.wav"
        return await self.upload_bytes(
            self.settings.gcs_output_bucket,
            object_name,
            content,
            "audio/wav",
        )

    async def upload_bytes(
        self,
        bucket_name: str,
        object_name: str,
        content: bytes,
        content_type: str,
    ) -> str:
        return await asyncio.to_thread(
            self._upload_bytes_sync,
            bucket_name,
            object_name,
            content,
            content_type,
        )

    async def download_bytes(self, gcs_path: str) -> bytes:
        return await asyncio.to_thread(self._download_bytes_sync, gcs_path)

    async def delete(self, gcs_path: str) -> None:
        await asyncio.to_thread(self._delete_sync, gcs_path)

    def _upload_bytes_sync(
        self,
        bucket_name: str,
        object_name: str,
        content: bytes,
        content_type: str,
    ) -> str:
        bucket = self._client_or_create().bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(content, content_type=content_type)
        return f"gs://{bucket_name}/{object_name}"

    def _download_bytes_sync(self, gcs_path: str) -> bytes:
        bucket_name, object_name = self._split_gcs_path(gcs_path)
        return self._client_or_create().bucket(bucket_name).blob(object_name).download_as_bytes()

    def _delete_sync(self, gcs_path: str) -> None:
        bucket_name, object_name = self._split_gcs_path(gcs_path)
        self._client_or_create().bucket(bucket_name).blob(object_name).delete()

    def _client_or_create(self) -> storage.Client:
        if self._client is None:
            self._client = storage.Client(project=self.settings.gcp_project_id or None)
        return self._client

    def _split_gcs_path(self, gcs_path: str) -> tuple[str, str]:
        prefix = "gs://"
        if not gcs_path.startswith(prefix):
            raise ValueError(f"Unsupported GCS path: {gcs_path}")
        bucket_name, _, object_name = gcs_path[len(prefix) :].partition("/")
        if not bucket_name or not object_name:
            raise ValueError(f"Unsupported GCS path: {gcs_path}")
        return bucket_name, object_name
