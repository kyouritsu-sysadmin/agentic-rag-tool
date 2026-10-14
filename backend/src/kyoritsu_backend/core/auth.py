from dataclasses import dataclass
from .errors import ApplicationError


@dataclass(frozen=True)
class Principal:
    subject: str
    companies: tuple[str, ...]
    admin: bool = False


def require_company(principal: Principal, company: str):
    if company not in principal.companies:
        raise ApplicationError(403, "Company is outside your access scope")
