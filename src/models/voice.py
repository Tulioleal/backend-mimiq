from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AudioHealthIssue(BaseModel):
    code: str
    message: str
    severity: str = "error"


class AudioHealthReport(BaseModel):
    passed: bool
    duration_seconds: float
    average_db: float
    peak_db: float
    noise_floor_db: float
    estimated_snr_db: float
    clipped_ratio: float
    issues: list[AudioHealthIssue]
    recommendations: list[str]


class VoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    duration: float
    gcs_path: str
    created_at: datetime


class VoiceCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    duration: float
    status: str
    created_at: datetime
    expires_at: datetime


class VoiceCandidateAnalyzeResponse(AudioHealthReport):
    candidate: VoiceCandidateRead


class VoiceCreateResponse(VoiceRead):
    health_report: AudioHealthReport
