from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db_session, require_admin
from models.metric import MetricRead

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", response_model=list[MetricRead], dependencies=[Depends(require_admin)])
async def list_metrics(
    request: Request,
    generation_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> list[MetricRead]:
    metrics = await request.app.state.services.generations.list_metrics(session, generation_id)
    return [MetricRead.model_validate(metric) for metric in metrics]
