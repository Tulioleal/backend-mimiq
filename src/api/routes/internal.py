from __future__ import annotations

import json
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db_session, require_internal_key, require_internal_key_websocket
from models.gpu import GPUStatusRead, TTSOfflineNotification, TTSStreamMetrics

router = APIRouter(prefix="/internal", tags=["internal"])


@router.websocket("/tts-worker/ws")
async def tts_worker_ws(
    websocket: WebSocket,
    _: str = Depends(require_internal_key_websocket),
) -> None:
    await websocket.accept()
    instance_id = (
        websocket.headers.get("x-instance-id")
        or websocket.query_params.get("instance_id")
    )
    session_maker = websocket.app.state.db.session_maker
    async with session_maker() as session:
        await websocket.app.state.services.tts_worker.connect(websocket)
        await websocket.app.state.services.gpu.mark_worker_connected(session, instance_id)

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await websocket.app.state.services.tts_worker.forward_audio_chunk(message["bytes"])
                continue
            if message.get("text") is not None:
                await _handle_worker_event(websocket, message["text"])
    except WebSocketDisconnect:
        pass
    finally:
        disconnected_active_worker = await websocket.app.state.services.tts_worker.disconnect(websocket)
        if disconnected_active_worker:
            async with session_maker() as session:
                await websocket.app.state.services.gpu.mark_worker_disconnected(
                    session,
                    instance_id,
                    "TTS worker disconnected.",
                )


@router.post("/tts-offline", response_model=GPUStatusRead)
async def register_tts_offline(
    payload: TTSOfflineNotification,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _: str = Depends(require_internal_key),
) -> GPUStatusRead:
    return await request.app.state.services.gpu.mark_offline(session, payload.instance_id, payload.reason)


@router.get("/jobs/{job_id}/speaker.wav")
async def download_job_speaker(
    job_id: str,
    request: Request,
    _: str = Depends(require_internal_key),
) -> Response:
    sample_bytes = await request.app.state.services.tts_worker.get_sample(job_id)
    if sample_bytes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return Response(
        content=sample_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": f'attachment; filename="{job_id}-speaker.wav"'},
    )


@router.post("/jobs/{job_id}/result")
async def upload_job_result(
    job_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
    gpu_time_ms: Annotated[int | None, Form()] = None,
    rtf: Annotated[float | None, Form()] = None,
    session: AsyncSession = Depends(get_db_session),
    _: str = Depends(require_internal_key),
) -> dict[str, str]:
    generation = await request.app.state.services.generations.get_generation(session, job_id)
    if generation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")
    if generation.metric is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Generation metric not started")

    audio_bytes = await file.read()
    output_gcs_path = await request.app.state.services.storage.upload_output(job_id, audio_bytes)
    await request.app.state.services.generations.complete_generation(
        session,
        generation,
        generation.metric,
        output_gcs_path,
        gpu_time_ms,
        rtf,
    )
    await request.app.state.services.tts_worker.complete_job(
        job_id,
        output_gcs_path,
        TTSStreamMetrics(gpu_time_ms=gpu_time_ms, rtf=rtf),
    )
    return {"status": "completed", "output_gcs_path": output_gcs_path}


async def _handle_worker_event(websocket: WebSocket, raw_message: str) -> None:
    try:
        event = json.loads(raw_message)
    except json.JSONDecodeError:
        await websocket.app.state.services.tts_worker.fail_active_job("Invalid TTS worker message")
        return

    event_type = event.get("type") or event.get("event")
    if event_type == "error":
        await websocket.app.state.services.tts_worker.fail_active_job(
            event.get("message") or "TTS worker error"
        )
