from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Voice


class VoiceService:
    async def list_voices(self, session: AsyncSession) -> list[Voice]:
        result = await session.execute(select(Voice).order_by(Voice.created_at.desc()))
        return list(result.scalars().all())

    async def get_voice(self, session: AsyncSession, voice_id: str) -> Voice | None:
        result = await session.execute(select(Voice).where(Voice.id == voice_id))
        return result.scalar_one_or_none()

    async def get_voice_with_generations(self, session: AsyncSession, voice_id: str) -> Voice | None:
        result = await session.execute(
            select(Voice)
            .options(selectinload(Voice.generations))
            .where(Voice.id == voice_id)
        )
        return result.scalar_one_or_none()

    async def create_voice(
        self,
        session: AsyncSession,
        name: str,
        duration: float,
        gcs_path: str,
    ) -> Voice:
        voice = Voice(name=name, duration=duration, gcs_path=gcs_path)
        session.add(voice)
        await session.commit()
        await session.refresh(voice)
        return voice

    async def delete_voice(self, session: AsyncSession, voice: Voice) -> None:
        await session.delete(voice)
        await session.commit()
