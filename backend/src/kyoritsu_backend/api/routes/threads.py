from kyoritsu_backend.schemas.chat import (
    BranchPage,
    HistoryResponse,
    RunResponse,
    ThreadPage,
    ThreadResponse,
)
from fastapi import APIRouter, Depends, Query
from ..deps import current_principal, application
from kyoritsu_backend.schemas.chat import ThreadCreate, ThreadPatch, SubmitMessage
from kyoritsu_backend.schemas.serialization import run_dict

router = APIRouter()


@router.post("/v1/threads", status_code=201, response_model=ThreadResponse)
async def create_thread(
    body: ThreadCreate, principal=Depends(current_principal), state=Depends(application)
):
    return await state.threads.create(body, principal)


@router.get("/v1/threads", response_model=ThreadPage)
async def list_threads(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    principal=Depends(current_principal),
    state=Depends(application),
):
    return await state.threads.list(principal, offset, limit)


@router.patch("/v1/threads/{thread_id}", response_model=ThreadResponse)
async def patch_thread(
    thread_id: str,
    body: ThreadPatch,
    principal=Depends(current_principal),
    state=Depends(application),
):
    return await state.threads.patch(thread_id, body, principal)


@router.delete("/v1/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str, principal=Depends(current_principal), state=Depends(application)
):
    await state.threads.delete(thread_id, principal)


@router.get("/v1/threads/{thread_id}/messages", response_model=HistoryResponse)
async def history(
    thread_id: str,
    head_id: str | None = None,
    limit: int = Query(100, ge=1, le=200),
    principal=Depends(current_principal),
    state=Depends(application),
):
    return await state.threads.history(thread_id, principal, head_id, limit)


@router.get("/v1/threads/{thread_id}/branches", response_model=BranchPage)
async def branches(
    thread_id: str,
    offset: int = Query(0, ge=0),
    principal=Depends(current_principal),
    state=Depends(application),
):
    return await state.threads.branches(thread_id, principal, offset)


@router.post("/v1/threads/{thread_id}/messages", status_code=202, response_model=RunResponse)
async def submit(
    thread_id: str,
    body: SubmitMessage,
    principal=Depends(current_principal),
    state=Depends(application),
):
    return run_dict(await state.chat.submit(thread_id, body, principal))
