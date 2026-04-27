from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Generation, Metric
from models.generation import GenerationCreateInput


class GenerationService:
    async def list_generations(self, session: AsyncSession) -> list[Generation]:
        result = await session.execute(
            select(Generation).order_by(Generation.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_generation(self, session: AsyncSession, generation_id: str) -> Generation | None:
        result = await session.execute(
            select(Generation)
            .options(selectinload(Generation.metric))
            .where(Generation.id == generation_id)
        )
        return result.scalar_one_or_none()

    async def create_generation(
        self,
        session: AsyncSession,
        payload: GenerationCreateInput,
    ) -> Generation:
        generation = Generation(
            voice_id=payload.voice_id,
            original_text=payload.original_text,
            style_prompt=payload.style_prompt,
            slider_config=payload.slider_config.model_dump(),
        )
        session.add(generation)
        await session.flush()
        return generation

    async def start_metric(self, session: AsyncSession, generation_id: str) -> Metric:
        metric = Metric(generation_id=generation_id)
        session.add(metric)
        await session.flush()
        return metric

    async def complete_generation(
        self,
        session: AsyncSession,
        generation: Generation,
        metric: Metric,
        output_gcs_path: str,
        gpu_time_ms: int | None,
        rtf: float | None,
    ) -> None:
        generation.output_gcs_path = output_gcs_path
        metric.gpu_time_ms = gpu_time_ms
        metric.rtf = rtf
        metric.completed_at = datetime.now(timezone.utc)
        await session.commit()

    async def list_metrics(
        self,
        session: AsyncSession,
        generation_id: str | None = None,
    ) -> list[Metric]:
        query = select(Metric).order_by(Metric.started_at.desc())
        if generation_id:
            query = query.where(Metric.generation_id == generation_id)
        result = await session.execute(query)
        return list(result.scalars().all())
