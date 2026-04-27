from __future__ import annotations

from fastapi import APIRouter

from api.routes import auth, generations, internal, metrics, status, voices
from api.websocket import router as websocket_router

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(status.router)
api_router.include_router(voices.router)
api_router.include_router(generations.router)
api_router.include_router(metrics.router)
api_router.include_router(internal.router)
api_router.include_router(websocket_router)
