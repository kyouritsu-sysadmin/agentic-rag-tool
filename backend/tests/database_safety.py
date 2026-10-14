"""Refuse destructive fixtures unless explicitly aimed at a dedicated test database."""

import os
import re
from sqlalchemy.engine import make_url


def disposable_database_url(value):
    if os.environ.get("RAG_ALLOW_TEST_DATABASE_RESET") != "1":
        raise ValueError("Set RAG_ALLOW_TEST_DATABASE_RESET=1 only for a disposable test database")
    try:
        url = make_url(value)
    except Exception:
        raise ValueError("Invalid test database URL") from None
    if (
        url.drivername != "postgresql+asyncpg"
        or url.username != "rag_test"
        or not re.fullmatch(r"rag_test(?:_[a-z0-9_]+)?", url.database or "")
        or url.query
    ):
        raise ValueError(
            "Tests require user rag_test and database rag_test or rag_test_<suffix>; URL overrides are forbidden"
        )
    return value
