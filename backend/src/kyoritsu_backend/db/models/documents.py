from datetime import date, datetime
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import VECTOR


from ..base import Base, now, uid


class Document(Base):
    __tablename__ = "documents"
    doc_id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    company: Mapped[str] = mapped_column(Text)
    dept: Mapped[str] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(Text, default="monthly_report")
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    meeting_date: Mapped[date | None]
    source_path: Mapped[str] = mapped_column(Text)
    active_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_versions.id", use_alter=True, name="fk_document_active_version")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("month BETWEEN 1 AND 12", name="ck_document_month"),)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="queued")
    pipeline: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_version_content", "doc_id", "content_hash"),)


class Chunk(Base):
    __tablename__ = "document_chunks"
    doc_chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True)
    chunk: Mapped[str] = mapped_column(Text)
    chunk_type: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(768))
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    company: Mapped[str] = mapped_column(Text)
    dept: Mapped[str] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(Text)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        Index("ix_chunks_scope", "company", "year", "month", "dept"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_vector",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
