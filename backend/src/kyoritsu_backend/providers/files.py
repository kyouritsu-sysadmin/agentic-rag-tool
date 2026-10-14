"""Local source adapters independent of the HTTP upload implementation."""

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
import asyncio


class UploadSource(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


@dataclass
class LocalUpload:
    file: BinaryIO
    filename: str

    async def read(self, size=-1):
        return await asyncio.to_thread(self.file.read, size)


@dataclass(frozen=True)
class SourceFile:
    path: Path
    filename: str
