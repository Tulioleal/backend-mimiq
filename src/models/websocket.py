from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from models.generation import GenerationCreateInput
from models.gpu import GPUStatus


class GenerationStartMessage(GenerationCreateInput):
    type: Literal["start_generation"] = "start_generation"


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    status: GPUStatus
    detail: str | None = None


class AcceptedMessage(BaseModel):
    type: Literal["accepted"] = "accepted"
    generation_id: str
    rewritten_text: str


class CompletedMessage(BaseModel):
    type: Literal["completed"] = "completed"
    generation_id: str
    output_gcs_path: str
    gpu_time_ms: int | None = None
    rtf: float | None = None


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    message: str
