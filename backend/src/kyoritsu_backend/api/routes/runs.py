from kyoritsu_backend.schemas.chat import RunDetail
import asyncio
import json
from kyoritsu_backend.services.chat import ACTIVE
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
from ..deps import current_principal, application

router = APIRouter()


@router.get("/v1/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, principal=Depends(current_principal), state=Depends(application)):
    return await state.runs.get(run_id, principal)


@router.post("/v1/runs/{run_id}/cancel", response_model=RunDetail)
async def cancel(run_id: str, principal=Depends(current_principal), state=Depends(application)):
    return await state.runs.cancel(run_id, principal)


@router.get("/v1/runs/{run_id}/events")
async def events(
    run_id: str, request: Request, principal=Depends(current_principal), state=Depends(application)
):
    await state.runs.authorize(run_id, principal)

    runs = state.runs

    async def stream():
        previous = None
        while not await request.is_disconnected():
            state = await runs.get(run_id, principal)
            # Snapshot events support reconnect without duplicate token replay.
            payload = json.dumps(
                jsonable_encoder({"type": "snapshot", **state}), ensure_ascii=False
            )
            if payload != previous:
                yield "data: " + payload + "\n\n"
                previous = payload
            if state["status"] not in ACTIVE:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "terminal",
                            **{key: value for key, value in state.items() if key != "message"},
                        }
                    )
                    + "\n\n"
                )
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
