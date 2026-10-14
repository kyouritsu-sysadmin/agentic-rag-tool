import asyncio
import re
import time
from sqlalchemy import select, func
from pydantic import ValidationError
from kyoritsu_backend.core.errors import ApplicationError
from kyoritsu_backend.db.models import Chunk, Document, DocumentVersion
from kyoritsu_backend.rag.planning import plan
from kyoritsu_backend.rag.fusion import fuse, balanced


class RetrievalService:
    def __init__(self, sessions, models, settings):
        self.sessions, self.models, self.settings = sessions, models, settings

    async def search_scope(self, scope, vector, query_text, limit):
        constraints = [
            Document.active_version_id == Chunk.version_id,
            DocumentVersion.status == "ready",
            Chunk.embedding.is_not(None),
            DocumentVersion.pipeline["embedding_model"].astext == self.settings.embed_model,
            DocumentVersion.pipeline["embedding_revision"].astext == self.settings.embed_revision,
            DocumentVersion.pipeline["backend"].astext == self.settings.model_backend,
        ]
        for field, value in scope.items():
            if value is not None:
                constraints.append(
                    getattr(Document if field == "meeting_date" else Chunk, field) == value
                )
        base = (
            select(Chunk.doc_chunk_id)
            .join(Document, Document.doc_id == Chunk.doc_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
            .where(*constraints)
        )

        async def lexical():
            if not query_text:
                return []
            tsquery = func.to_tsquery("simple", query_text)
            stmt = (
                base.where(Chunk.tsv.op("@@")(tsquery))
                .order_by(func.ts_rank(Chunk.tsv, tsquery).desc(), Chunk.doc_chunk_id)
                .limit(limit)
            )
            async with self.sessions() as session:
                return list((await session.scalars(stmt)).all())

        async def semantic():
            stmt = base.order_by(Chunk.embedding.cosine_distance(vector), Chunk.doc_chunk_id).limit(
                limit
            )
            async with self.sessions() as session:
                return list((await session.scalars(stmt)).all())

        lexical_ids, vector_ids = await asyncio.gather(lexical(), semantic())
        ranking = fuse(lexical_ids, vector_ids)[:limit]
        if not ranking:
            return []
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(Chunk, Document.meeting_date, DocumentVersion.file_name)
                    .join(Document, Document.doc_id == Chunk.doc_id)
                    .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
                    .where(Chunk.doc_chunk_id.in_([i for i, _ in ranking]), *constraints)
                )
            ).all()
            data = {
                c.doc_chunk_id: dict(
                    doc_chunk_id=c.doc_chunk_id,
                    doc_id=c.doc_id,
                    version_id=c.version_id,
                    chunk=c.chunk,
                    chunk_type=c.chunk_type,
                    company=c.company,
                    dept=c.dept,
                    section=c.section,
                    doc_type=c.doc_type,
                    year=c.year,
                    month=c.month,
                    meeting_date=str(meeting) if meeting else None,
                    rerank_score=None,
                    file_name=name,
                    provenance=c.provenance,
                )
                for c, meeting, name in rows
            }
        return [dict(data[key], rrf_score=score) for key, score in ranking if key in data]

    async def retrieve(self, request, principal):
        start = time.perf_counter()
        scopes = plan(request, principal)
        vector = await self.models.embed(request.query)
        tokens = await self.models.tokens(request.query)
        # Quote each lexeme; punctuation never becomes a tsquery operator.
        tokens = [re.sub(r"[^\w\-]", "", t) for t in tokens]
        query_text = " | ".join("'" + t + "'" for t in tokens if t)
        limit = max(50, request.top_k * 2)
        groups = []
        for scope in scopes:
            candidates = await self.search_scope(scope, vector, query_text, limit)
            if not request.no_rerank and candidates:
                candidates = await self.models.rerank(request.query, candidates)
            groups.append(candidates)
        chunks = balanced(groups, request.top_k)
        returned_ids = {c["doc_chunk_id"] for c in chunks}
        coverage = [
            dict(
                scope=s,
                candidates=len(g),
                returned=sum(c["doc_chunk_id"] in returned_ids for c in g),
            )
            for s, g in zip(scopes, groups)
        ]
        applied = {
            key: scopes[0][key] if all(s[key] == scopes[0][key] for s in scopes) else None
            for key in ("company", "dept", "section", "doc_type", "year", "month")
        }
        return dict(
            chunks=chunks,
            count=len(chunks),
            filters_applied=applied,
            scopes=scopes,
            coverage=coverage,
            elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    async def retrieve_bounded(self, request, principal):
        try:
            async with asyncio.timeout(self.settings.request_timeout):
                return await self.retrieve(request, principal)
        except (ValueError, ValidationError) as exc:
            raise ApplicationError(422, "Invalid inferred period or date") from exc
        except TimeoutError as exc:
            raise ApplicationError(504, "Retrieval timed out") from exc
