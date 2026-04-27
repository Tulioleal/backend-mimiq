from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Header, HTTPException, Request, WebSocket, WebSocketException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from services import AppServices


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_services(request: Request) -> AppServices:
    return request.app.state.services


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_maker = request.app.state.db.session_maker
    async with session_maker() as session:
        yield session


async def require_admin(
    request: Request,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> str:
    settings = get_settings(request)
    services = get_services(request)
    candidate = request.cookies.get(settings.cookie_name) or x_admin_key
    if not services.auth.is_authorized(candidate):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")
    return candidate or ""


async def require_internal_key(
    request: Request,
    x_internal_key: str | None = Header(default=None, alias="X-Internal-Key"),
) -> str:
    settings = get_settings(request)
    if not settings.internal_secret or settings.internal_secret != x_internal_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal key")
    return x_internal_key or ""


async def require_admin_websocket(websocket: WebSocket) -> str:
    settings = websocket.app.state.settings
    services = websocket.app.state.services
    candidate = websocket.cookies.get(settings.cookie_name) or websocket.headers.get("X-Admin-Key")
    if not services.auth.is_authorized(candidate):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid admin key",
        )
    return candidate or ""
