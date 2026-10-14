from .base import ResponseModel


class ModelResponse(ResponseModel):
    id: str
    name: str
    streaming: bool
    attachments: bool
    loaded: bool


class ModelPage(ResponseModel):
    models: list[ModelResponse]


class ModelReady(ResponseModel):
    loaded: bool
