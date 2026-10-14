from .base import ResponseModel


class JobAccepted(ResponseModel):
    job_id: str
    version_id: str
    status: str


class JobResponse(ResponseModel):
    id: str
    document_id: str
    version_id: str
    status: str
    attempts: int
    progress: int
    error: str | None
