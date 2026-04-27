from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db_session, require_admin
from models.gpu import GPUStatusRead

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("/gpu", response_model=GPUStatusRead, dependencies=[Depends(require_admin)])
async def gpu_status(request: Request, session: AsyncSession = Depends(get_db_session)) -> GPUStatusRead:
    return await request.app.state.services.gpu.get_status(session)
