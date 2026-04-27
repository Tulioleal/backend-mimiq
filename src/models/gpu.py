from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class GPUStatus(str, Enum):
    OFFLINE = "offline"
    BOOTING = "booting"
    READY = "ready"


class GPUStatusRead(BaseModel):
    status: GPUStatus
    instance_id: str | None = None
    endpoint: str | None = None
    detail: str | None = None


class TTSReadyRegistration(BaseModel):
    endpoint: str
    instance_id: str | None = None


class TTSOfflineNotification(BaseModel):
    instance_id: str | None = None
    reason: str | None = None


class TTSStreamMetrics(BaseModel):
    gpu_time_ms: int | None = None
    rtf: float | None = None


class UpstreamStartPayload(BaseModel):
    event: str = "start"
    text: str
    language: str
    slider_config: dict[str, float]
    sample_filename: str = Field(default="voice-sample.wav")
    sample_content_type: str = Field(default="audio/wav")
