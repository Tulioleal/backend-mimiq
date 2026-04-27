from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SliderConfig(BaseModel):
    temperature: float = Field(default=0.7, ge=0.1, le=1.0)
    speech_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    repetition_penalty: float = Field(default=2.0, ge=1.0, le=10.0)


class GenerationCreateInput(BaseModel):
    voice_id: str
    original_text: str = Field(min_length=1)
    style_prompt: str = Field(min_length=1)
    language: str = Field(default="es", min_length=2, max_length=8)
    slider_config: SliderConfig


class GenerationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    voice_id: str
    original_text: str
    style_prompt: str
    slider_config: dict[str, float]
    output_gcs_path: str | None
    created_at: datetime
