from pydantic import BaseModel, Field


class RetrieveRequest(BaseModel):
    query:     str
    company:   str | None = None
    dept:      str | None = None
    section:   str | None = None
    year:      int | None = None
    month:     int | None = None
    doc_type:  str | None = None
    top_k:     int        = Field(default=8, ge=1, le=50)
    no_rerank: bool       = False


class ChunkOut(BaseModel):
    doc_chunk_id: str
    doc_id:       str
    chunk:        str
    chunk_type:   str
    company:      str
    dept:         str
    section:      str | None
    doc_type:     str
    year:         int
    month:        int
    meeting_date: str | None
    rrf_score:    float
    rerank_score: float | None


class FiltersApplied(BaseModel):
    company:  str | None
    dept:     str | None
    section:  str | None
    year:     int | None
    month:    int | None
    doc_type: str | None


class RetrieveResponse(BaseModel):
    chunks:          list[ChunkOut]
    count:           int
    filters_applied: FiltersApplied
