from datetime import date
from pydantic import Field
from .base import ScopeSchema
from .base import ResponseModel


class DocumentMetadata(ScopeSchema):
    company: str = Field(min_length=1)
    dept: str = Field(min_length=1)
    section: str | None = None
    doc_type: str = "monthly_report"
    year: int = Field(ge=1900, le=2200)
    month: int = Field(ge=1, le=12)
    meeting_date: date | None = None
    document_id: str | None = None
    import_key: str = Field(min_length=8, max_length=128)


class DocumentResponse(ResponseModel):
    id: str
    company: str
    dept: str
    year: int
    month: int
    active_version_id: str | None


class DocumentPage(ResponseModel):
    documents: list[DocumentResponse]
    next_offset: int | None
