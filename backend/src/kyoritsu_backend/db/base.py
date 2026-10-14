from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy.orm import DeclarativeBase


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass
