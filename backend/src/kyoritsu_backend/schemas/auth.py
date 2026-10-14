from .base import ResponseModel


class PrincipalResponse(ResponseModel):
    subject: str
    companies: list[str]
    admin: bool
