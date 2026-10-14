"""Durable PostgreSQL job worker. Lease fencing prevents stale workers publishing."""

import asyncio
import logging
import json
import os
import signal
import sys
from datetime import timedelta
from sqlalchemy import select, or_, and_, func
from kyoritsu_backend.core.settings import Settings
from kyoritsu_backend.db.session import create_database
from kyoritsu_backend.db.models import IngestionJob, DocumentVersion, Document, Chunk, now, uid
from kyoritsu_backend.providers.models import ModelProvider
from kyoritsu_backend.providers.summaries import summarize
from kyoritsu_backend.rag.pipeline import indexing_configuration
from kyoritsu_backend.rag.chunking import split_content
from kyoritsu_backend.services.documents import source_path

logger = logging.getLogger(__name__)


async def run_parser(command, timeout):
    """Kill and reap the parser process group on timeout or cancellation."""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await process.communicate()
        if process.returncode:
            raise RuntimeError("Parser process failed: " + stderr.decode(errors="replace")[-2000:])
        return json.loads(stdout)
    finally:
        # Include parser children (e.g. OCR), even if the direct child already exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.communicate()


async def parse_pages(path, settings):
    return await run_parser(
        [sys.executable, "-m", "kyoritsu_backend.workers.parser", str(path), settings.parser],
        settings.parser_timeout,
    )


async def process_one(sessions, models, settings):
    async with sessions.begin() as session:
        job = await session.scalar(
            select(IngestionJob)
            .where(
                or_(
                    IngestionJob.status == "queued",
                    and_(IngestionJob.status == "running", IngestionJob.lease_until < now()),
                )
            )
            .order_by(IngestionJob.created_at, IngestionJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return False
        if job.attempts >= settings.max_job_attempts:
            job.status, job.error = "failed", "Maximum attempts reached after expired lease"
            (await session.get(DocumentVersion, job.version_id)).status = "failed"
            return True
        job.status, job.attempts, job.lease_token = "running", job.attempts + 1, uid()
        job.lease_until = now() + timedelta(seconds=settings.job_lease_seconds)
        job_id, lease = job.id, job.lease_token
        version = await session.get(DocumentVersion, job.version_id)
        version.status = "processing"
        doc = await session.get(Document, version.doc_id)
        # Do not publish an index built with different API/worker settings.
        requested = version.pipeline.get("requested")
        try:
            pipeline = indexing_configuration(settings)
        except ValueError:
            pipeline = None
        if requested is None or requested != pipeline:
            job.status, version.status = "failed", "failed"
            job.lease_until = None
            job.error = (
                "Index configuration mismatch or legacy job without a configuration snapshot; "
                "align API/worker settings and retry, or re-upload with a new import key"
            )
            return True

    async def heartbeat():
        while True:
            await asyncio.sleep(settings.job_lease_seconds / 3)
            async with sessions.begin() as session:
                current = await session.get(IngestionJob, job_id, with_for_update=True)
                if current.lease_token != lease or current.status != "running":
                    raise RuntimeError("Ingestion lease ownership lost")
                current.lease_until = now() + timedelta(seconds=settings.job_lease_seconds)

    async def work():
        pages = await parse_pages(source_path(settings, version.storage_key), settings)
        chunks = []
        for page, content in pages:
            for part in await split_content(content, models.token_count):
                text, kind = part["text"], part["chunk_type"]
                vector = await models.embed(text, document=True)
                tokens = await models.tokens(text)
                summary = await summarize(settings, text)
                chunks.append(
                    Chunk(
                        doc_chunk_id=f"{version.id}:{len(chunks):06d}",
                        doc_id=doc.doc_id,
                        version_id=version.id,
                        chunk=text,
                        chunk_type=kind,
                        summary=summary,
                        embedding=vector,
                        tsv=func.to_tsvector("simple", " ".join(tokens)),
                        **{
                            k: getattr(doc, k)
                            for k in ("company", "dept", "section", "doc_type", "year", "month")
                        },
                        provenance={
                            "page": page,
                            "ordinal": len(chunks),
                            "heading": part["heading"],
                            "parser": settings.parser,
                        },
                    )
                )
        if not chunks:
            raise ValueError("No extractable text; use the OCR parser for scanned PDFs")
        async with sessions.begin() as session:
            current = await session.get(IngestionJob, job_id, with_for_update=True)
            if current.lease_token != lease or current.status != "running":
                return True
            session.add_all(chunks)
            await session.flush()
            current_version = await session.get(DocumentVersion, version.id)
            current_version.status = "ready"
            current_version.pipeline = {
                **current_version.pipeline,
                **pipeline,
            }
            current_doc = await session.get(Document, doc.doc_id, with_for_update=True)
            # A delayed old job must not replace a newer successfully published version.
            active = (
                await session.get(DocumentVersion, current_doc.active_version_id)
                if current_doc.active_version_id
                else None
            )
            if not active or active.created_at <= current_version.created_at:
                current_doc.active_version_id = version.id
            current.status, current.progress, current.error, current.lease_until = (
                "completed",
                100,
                None,
                None,
            )

    try:
        async with asyncio.TaskGroup() as group:
            pulse = group.create_task(heartbeat())
            task = group.create_task(work())
            try:
                await task
            finally:
                pulse.cancel()
    except asyncio.CancelledError:
        raise  # Lease expiry makes an interrupted job retryable.
    except Exception:
        logger.exception("Ingestion failed: job=%s", job_id)
        async with sessions.begin() as session:
            current = await session.get(IngestionJob, job_id, with_for_update=True)
            if current.lease_token == lease and current.status == "running":
                current.status = "failed"
                current.error = "Document processing failed; inspect worker logs using job ID"
                (await session.get(DocumentVersion, version.id)).status = "failed"
    return True


async def worker_loop(sessions, models, settings):
    delay = 1.0
    while True:
        try:
            processed = await process_one(sessions, models, settings)
            delay = 1.0
            if not processed:
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Includes claim/heartbeat/failure-persistence errors during DB outages.
            # The lease makes abandoned work eligible again after reconnection.
            logger.exception("Worker iteration failed; retrying in %.1fs", delay)
            await asyncio.sleep(min(delay, settings.worker_retry_max_seconds))
            delay = min(delay * 2, settings.worker_retry_max_seconds)


async def run():
    settings = Settings()
    if settings.device != "cpu":
        raise SystemExit("This worker requires RAG_DEVICE=cpu; the API owns the inference GPU")
    import os

    os.environ["TORCH_DEVICE"] = "cpu"
    settings.validate_model_revisions()
    engine, sessions = create_database(settings.database_url.get_secret_value())
    models = ModelProvider(settings)
    try:
        await worker_loop(sessions, models, settings)
    finally:
        await models.close()
        await engine.dispose()


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
