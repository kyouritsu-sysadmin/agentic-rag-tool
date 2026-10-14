"""Register all mapped domains, including migrations and CLI metadata discovery."""

from ..base import Base as Base, now as now, uid as uid
from .documents import Document as Document, DocumentVersion as DocumentVersion, Chunk as Chunk
from .ingestion import IngestionJob as IngestionJob
from .chat import (
    Thread as Thread,
    Message as Message,
    GenerationRun as GenerationRun,
    MessageSource as MessageSource,
)
