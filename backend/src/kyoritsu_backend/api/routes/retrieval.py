from kyoritsu_backend.schemas.retrieval import RetrievalResponse
from fastapi import APIRouter, Depends
from ..deps import current_principal, application
from kyoritsu_backend.schemas.retrieval import RetrievalRequest

router = APIRouter()


@router.post("/v1/tool/retrieval", response_model=RetrievalResponse)
async def retrieval(
    body: RetrievalRequest, principal=Depends(current_principal), state=Depends(application)
):
    return await state.retrieval.retrieve_bounded(body, principal)
