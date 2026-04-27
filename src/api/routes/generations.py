from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db_session, require_admin
from models.generation import GenerationRead
from utils.audio import guess_audio_media_type

router = APIRouter(prefix="/api/generations", tags=["generations"])


@router.get("", response_model=list[GenerationRead], dependencies=[Depends(require_admin)])
async def list_generations(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[GenerationRead]:
    generations = await request.app.state.services.generations.list_generations(session)
    return [GenerationRead.model_validate(generation) for generation in generations]


@router.get("/{generation_id}", response_model=GenerationRead, dependencies=[Depends(require_admin)])
async def get_generation(
    generation_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> GenerationRead:
    generation = await request.app.state.services.generations.get_generation(session, generation_id)
    if generation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")
    return GenerationRead.model_validate(generation)


@router.get(
    "/{generation_id}/audio",
    dependencies=[Depends(require_admin)],
)
async def download_generation_audio(
    generation_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    generation = await request.app.state.services.generations.get_generation(session, generation_id)
    if generation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")
    if not generation.output_gcs_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation output is not available yet",
        )

    audio_bytes = await request.app.state.services.storage.download_bytes(generation.output_gcs_path)
    return Response(
        content=audio_bytes,
        media_type=guess_audio_media_type(generation.output_gcs_path),
        headers={"Content-Disposition": f'attachment; filename="{generation.id}.wav"'},
    )
