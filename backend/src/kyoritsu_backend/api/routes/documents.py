from kyoritsu_backend.schemas.documents import DocumentPage
from kyoritsu_backend.schemas.ingestion import JobAccepted
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import ValidationError
from ..deps import current_principal, application
from kyoritsu_backend.schemas.documents import DocumentMetadata

router = APIRouter()


@router.post("/v1/documents", status_code=202, response_model=JobAccepted)
async def upload_document(
    metadata: str = Form(...),
    file: UploadFile = File(...),
    principal=Depends(current_principal),
    state=Depends(application),
):
    try:
        parsed = DocumentMetadata.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid document metadata") from exc
    return await state.documents.upload(parsed, file, principal)


@router.post("/v1/documents/{doc_id}/reindex", status_code=202, response_model=JobAccepted)
async def reindex(
    doc_id: str,
    import_key: str = Query(min_length=8, max_length=128),
    principal=Depends(current_principal),
    state=Depends(application),
):
    return await state.documents.reindex(doc_id, import_key, principal)


@router.get("/v1/documents", response_model=DocumentPage)
async def list_documents(
    offset: int = Query(0, ge=0), principal=Depends(current_principal), state=Depends(application)
):
    return await state.documents.list(principal, offset)


@router.get("/v1/documents/{doc_id}/versions/{version_id}/source")
async def source(
    doc_id: str, version_id: str, principal=Depends(current_principal), state=Depends(application)
):
    source = await state.documents.source(doc_id, version_id, principal)
    return FileResponse(
        source.path, filename=source.filename, content_disposition_type="attachment"
    )
