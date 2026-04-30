from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Voice, VoiceCandidate
from models.voice import AudioHealthReport


PENDING = "pending"
CONFIRMED = "confirmed"
DISCARDED = "discarded"


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


class VoiceCandidateService:
    async def create_candidate(
        self,
        session: AsyncSession,
        name: str,
        duration: float,
        gcs_path: str,
        health_report: AudioHealthReport,
    ) -> VoiceCandidate:
        candidate = VoiceCandidate(
            name=name,
            duration=duration,
            gcs_path=gcs_path,
            health_report=health_report.model_dump(mode="json"),
            status=PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        session.add(candidate)
        await session.commit()
        await session.refresh(candidate)
        return candidate

    async def get_candidate(
        self,
        session: AsyncSession,
        candidate_id: str,
    ) -> VoiceCandidate | None:
        result = await session.execute(
            select(VoiceCandidate).where(VoiceCandidate.id == candidate_id)
        )
        return result.scalar_one_or_none()

    async def confirm_candidate(
        self,
        session: AsyncSession,
        candidate: VoiceCandidate,
    ) -> Voice:
        voice = Voice(
            name=candidate.name,
            duration=candidate.duration,
            gcs_path=candidate.gcs_path,
        )
        session.add(voice)
        await session.flush()
        candidate.status = CONFIRMED
        candidate.confirmed_voice_id = voice.id
        await session.commit()
        await session.refresh(voice)
        return voice

    async def discard_candidate(self, session: AsyncSession, candidate: VoiceCandidate) -> None:
        candidate.status = DISCARDED
        await session.commit()
