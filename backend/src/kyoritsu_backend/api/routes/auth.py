from kyoritsu_backend.schemas.auth import PrincipalResponse
from fastapi import APIRouter, Depends
from ..deps import current_principal, application

router = APIRouter()


@router.get("/v1/me", response_model=PrincipalResponse)
async def me(principal=Depends(current_principal), state=Depends(application)):
    return principal
