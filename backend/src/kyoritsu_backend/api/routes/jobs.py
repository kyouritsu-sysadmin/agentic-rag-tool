from kyoritsu_backend.schemas.ingestion import JobResponse
from fastapi import APIRouter, Depends
from ..deps import current_principal, application

router = APIRouter()


@router.get("/v1/jobs/{job_id}", response_model=JobResponse)
async def job_status(job_id: str, principal=Depends(current_principal), state=Depends(application)):
    return await state.jobs.status(job_id, principal)


@router.post("/v1/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(job_id: str, principal=Depends(current_principal), state=Depends(application)):
    return await state.jobs.retry(job_id, principal)
