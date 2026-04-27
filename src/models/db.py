from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Voice(Base):
    __tablename__ = "voices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    gcs_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    generations: Mapped[list["Generation"]] = relationship(
        back_populates="voice",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    voice_id: Mapped[str] = mapped_column(
        ForeignKey("voices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    style_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    slider_config: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    output_gcs_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    voice: Mapped[Voice] = relationship(back_populates="generations")
    metric: Mapped["Metric | None"] = relationship(
        back_populates="generation",
        cascade="all, delete-orphan",
        uselist=False,
        passive_deletes=True,
    )


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    generation_id: Mapped[str] = mapped_column(
        ForeignKey("generations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    gpu_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rtf: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    generation: Mapped[Generation] = relationship(back_populates="metric")


class TTSRuntimeState(Base):
    __tablename__ = "tts_runtime_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
