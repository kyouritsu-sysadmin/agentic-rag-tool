from kyoritsu_backend.schemas.models import ModelPage, ModelReady
from fastapi import APIRouter, Depends
from ..deps import current_principal, application

router = APIRouter()


@router.get("/v1/models", response_model=ModelPage)
async def models(principal=Depends(current_principal), state=Depends(application)):
    return state.catalog.list()


@router.post("/v1/models/warmup", response_model=ModelReady)
async def warmup(principal=Depends(current_principal), state=Depends(application)):
    return await state.catalog.warmup(principal)
