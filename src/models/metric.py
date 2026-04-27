from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    generation_id: str
    gpu_time_ms: int | None
    rtf: float | None
    started_at: datetime
    completed_at: datetime | None
