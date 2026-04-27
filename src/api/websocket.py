from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from api.deps import require_admin_websocket
from core.exceptions import ConfigurationError, GPUNotReadyError, UpstreamTTSError
from models.websocket import ErrorMessage, GenerationStartMessage

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/generations/stream")
async def generation_stream(
    websocket: WebSocket,
    _: str = Depends(require_admin_websocket),
) -> None:
    await websocket.accept()
    session_maker = websocket.app.state.db.session_maker
    async with session_maker() as session:
        try:
            payload = GenerationStartMessage.model_validate(await websocket.receive_json())
            await websocket.app.state.services.tts_proxy.proxy_generation(
                websocket,
                session,
                payload,
            )
        except GPUNotReadyError as exc:
            await websocket.send_json(ErrorMessage(message=exc.status.detail or str(exc)).model_dump())
            await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        except (ConfigurationError, UpstreamTTSError, RuntimeError, ValueError) as exc:
            await websocket.send_json(ErrorMessage(message=str(exc)).model_dump())
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except ValidationError as exc:
            await websocket.send_json(ErrorMessage(message=str(exc)).model_dump())
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
        except WebSocketDisconnect:
            return
