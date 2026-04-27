from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db_session, require_internal_key
from models.gpu import GPUStatusRead, TTSOfflineNotification, TTSReadyRegistration

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/tts-ready", response_model=GPUStatusRead)
async def register_tts_ready(
    payload: TTSReadyRegistration,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: str = Depends(require_internal_key),
) -> GPUStatusRead:
    return await request.app.state.services.gpu.register_tts_endpoint(
        session,
        payload.endpoint,
        payload.instance_id,
    )


@router.post("/tts-offline", response_model=GPUStatusRead)
async def register_tts_offline(
    payload: TTSOfflineNotification,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: str = Depends(require_internal_key),
) -> GPUStatusRead:
    return await request.app.state.services.gpu.mark_offline(session, payload.instance_id, payload.reason)
