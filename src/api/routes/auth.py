from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from api.deps import require_admin
from models.auth import LoginRequest, SessionResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=SessionResponse)
async def login(
    request: Request,
    payload: Annotated[LoginRequest | None, Body()] = None,
    x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None,
) -> JSONResponse:
    services = request.app.state.services
    settings = request.app.state.settings
    candidate = x_admin_key or (payload.admin_key if payload else None)
    if not services.auth.is_authorized(candidate):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")

    response = JSONResponse(content=SessionResponse(authenticated=True).model_dump())
    response.set_cookie(
        key=settings.cookie_name,
        value=candidate,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.cookie_max_age_seconds,
        expires=settings.cookie_max_age_seconds,
        path="/",
    )
    return response


@router.post("/logout", response_model=SessionResponse)
async def logout(request: Request, _: str = Depends(require_admin)) -> JSONResponse:
    settings = request.app.state.settings
    response = JSONResponse(content=SessionResponse(authenticated=False).model_dump())
    response.delete_cookie(key=settings.cookie_name, path="/")
    return response


@router.get("/session", response_model=SessionResponse)
async def session_status(_: str = Depends(require_admin)) -> SessionResponse:
    return SessionResponse(authenticated=True)
