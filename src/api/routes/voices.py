from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db_session, require_admin
from models.voice import (
    AudioHealthReport,
    VoiceCandidateAnalyzeResponse,
    VoiceCandidateRead,
    VoiceCreateResponse,
    VoiceRead,
)
from utils.audio import guess_audio_media_type

router = APIRouter(prefix="/api/voices", tags=["voices"])


def is_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


@router.post(
    "/analyze",
    response_model=VoiceCandidateAnalyzeResponse,
    dependencies=[Depends(require_admin)],
)
async def analyze_voice(
    request: Request,
    name: str = Form(...),
    audio: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> VoiceCandidateAnalyzeResponse:
    audio_bytes, report = await request.app.state.services.audio_health.analyze_upload(audio)
    gcs_path = await request.app.state.services.storage.upload_sample(
        audio_bytes,
        audio.content_type,
        audio.filename,
    )
    candidate = await request.app.state.services.voice_candidates.create_candidate(
        session,
        name=name,
        duration=report.duration_seconds,
        gcs_path=gcs_path,
        health_report=report,
    )
    return VoiceCandidateAnalyzeResponse.model_validate({
        **report.model_dump(mode="json"),
        "candidate": VoiceCandidateRead.model_validate(candidate).model_dump(mode="json"),
    })


@router.post(
    "/candidates/{candidate_id}/confirm",
    response_model=VoiceCreateResponse,
    dependencies=[Depends(require_admin)],
)
async def confirm_voice_candidate(
    candidate_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> VoiceCreateResponse:
    candidate = await request.app.state.services.voice_candidates.get_candidate(session, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice candidate not found")
    if candidate.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Voice candidate is not pending")
    if is_expired(candidate.expires_at):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Voice candidate expired")

    voice = await request.app.state.services.voice_candidates.confirm_candidate(session, candidate)
    report = AudioHealthReport.model_validate(candidate.health_report)
    return VoiceCreateResponse.model_validate({
        **VoiceRead.model_validate(voice).model_dump(mode="json"),
        "health_report": report.model_dump(mode="json"),
    })


@router.delete(
    "/candidates/{candidate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def discard_voice_candidate(
    candidate_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    candidate = await request.app.state.services.voice_candidates.get_candidate(session, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice candidate not found")
    if candidate.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Voice candidate is not pending")

    await request.app.state.services.storage.delete(candidate.gcs_path)
    await request.app.state.services.voice_candidates.discard_candidate(session, candidate)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=list[VoiceRead], dependencies=[Depends(require_admin)])
async def list_voices(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[VoiceRead]:
    voices = await request.app.state.services.voices.list_voices(session)
    return [VoiceRead.model_validate(voice) for voice in voices]


@router.post("", response_model=VoiceCreateResponse, dependencies=[Depends(require_admin)])
async def create_voice(
    request: Request,
    name: str = Form(...),
    audio: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> VoiceCreateResponse:
    audio_bytes, report = await request.app.state.services.audio_health.analyze_upload(audio)
    gcs_path = await request.app.state.services.storage.upload_sample(
        audio_bytes,
        audio.content_type,
        audio.filename,
    )
    voice = await request.app.state.services.voices.create_voice(
        session,
        name=name,
        duration=report.duration_seconds,
        gcs_path=gcs_path,
    )
    return VoiceCreateResponse.model_validate({
        **VoiceRead.model_validate(voice).model_dump(mode="json"),
        "health_report": report.model_dump(mode="json"),
    })


@router.get("/{voice_id}/audio", dependencies=[Depends(require_admin)])
async def get_voice_audio(
    voice_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    voice = await request.app.state.services.voices.get_voice(session, voice_id)
    if voice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice not found")

    audio_bytes = await request.app.state.services.storage.download_bytes(voice.gcs_path)
    return Response(
        content=audio_bytes,
        media_type=guess_audio_media_type(voice.gcs_path),
        headers={"Content-Disposition": f'inline; filename="{voice.name}"'},
    )


@router.delete("/{voice_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_voice(
    voice_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    voice = await request.app.state.services.voices.get_voice_with_generations(session, voice_id)
    if voice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice not found")

    delete_paths = [voice.gcs_path, *[gen.output_gcs_path for gen in voice.generations if gen.output_gcs_path]]
    for path in delete_paths:
        await request.app.state.services.storage.delete(path)

    await request.app.state.services.voices.delete_voice(session, voice)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
