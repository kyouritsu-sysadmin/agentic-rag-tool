from pydantic import Field, field_validator
from .base import Schema
from datetime import datetime
from typing import Any, Literal
from .base import ResponseModel


class SubmitMessage(Schema):
    text: str = Field(min_length=1, max_length=4000)
    model_id: str = "default"
    parent_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)


class ThreadCreate(Schema):
    title: str | None = Field(default=None, max_length=200)


class ThreadPatch(Schema):
    title: str | None = Field(default=None, max_length=200)
    status: str | None = None
    head_id: str | None = None

    @field_validator("status")
    @classmethod
    def known_status(cls, value):
        if value not in {None, "regular", "archived"}:
            raise ValueError("Invalid thread status")
        return value


class Citation(ResponseModel):
    doc_id: str
    chunk_id: str
    version_id: str
    file_name: str
    folder: str
    source_url: str
    provenance: dict[str, Any]


class MessageResponse(ResponseModel):
    id: str
    parent_id: str | None
    role: Literal["user", "assistant"]
    text: str
    status: str
    createdAt: datetime
    citations: list[Citation]


class ThreadResponse(ResponseModel):
    id: str
    title: str | None
    status: Literal["regular", "archived"]
    head_id: str | None
    createdAt: datetime


class ThreadPage(ResponseModel):
    threads: list[ThreadResponse]
    next_offset: int | None


class RunResponse(ResponseModel):
    id: str
    thread_id: str
    user_message_id: str
    assistant_message_id: str
    status: str
    error: str | None


class RunDetail(RunResponse):
    message: MessageResponse


class HistoryResponse(ResponseModel):
    messages: list[MessageResponse]
    older_head_id: str | None
    active_run: RunResponse | None


class Branch(ResponseModel):
    id: str
    preview: str
    status: str


class BranchPage(ResponseModel):
    head_id: str | None
    branches: list[Branch]
    next_offset: int | None
