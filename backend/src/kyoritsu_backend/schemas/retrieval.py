from datetime import date
from pydantic import Field, model_validator
from .base import Schema, ScopeSchema
from typing import Any
from .base import ResponseModel


class Period(Schema):
    year: int | None = Field(default=None, ge=1900, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)


class RetrievalRequest(ScopeSchema):
    query: str = Field(min_length=1, max_length=4000)
    company: str | None = None
    dept: str | None = None
    section: str | None = None
    doc_type: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)
    meeting_date: date | None = None
    periods: list[Period] | None = Field(default=None, min_length=1, max_length=12)
    top_k: int = Field(default=8, ge=1, le=50)
    no_rerank: bool = True

    @model_validator(mode="after")
    def disjoint_periods(self):
        if self.periods and (self.year is not None or self.month is not None):
            raise ValueError("Use periods or year/month, not both")
        return self


class AppliedFilters(ResponseModel):
    company: str | None
    dept: str | None
    section: str | None
    doc_type: str | None
    year: int | None
    month: int | None


class RetrievalScope(AppliedFilters):
    meeting_date: date | None


class ScopeCoverage(ResponseModel):
    scope: RetrievalScope
    candidates: int
    returned: int


class RetrievedChunk(ResponseModel):
    doc_chunk_id: str
    doc_id: str
    version_id: str
    chunk: str
    chunk_type: str
    company: str
    dept: str
    section: str | None
    doc_type: str
    year: int
    month: int
    meeting_date: date | None
    rerank_score: float | None
    file_name: str
    provenance: dict[str, Any]
    rrf_score: float


class RetrievalResponse(ResponseModel):
    chunks: list[RetrievedChunk]
    count: int
    filters_applied: AppliedFilters
    scopes: list[RetrievalScope]
    coverage: list[ScopeCoverage]
    elapsed_ms: float
