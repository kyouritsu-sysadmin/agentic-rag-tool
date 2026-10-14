from kyoritsu_backend.schemas.documents import DocumentMetadata
from kyoritsu_backend.providers.files import LocalUpload, SourceFile, UploadSource
import hashlib
import json
from pathlib import Path
from kyoritsu_backend.core.errors import ApplicationError
from sqlalchemy import select
from kyoritsu_backend.core.auth import require_company
from kyoritsu_backend.db.models import Document, DocumentVersion, IngestionJob
from kyoritsu_backend.rag.pipeline import indexing_configuration


def source_path(settings, key):
    root = settings.storage_dir.resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise ApplicationError(404, "Source not found")
    return path


async def enqueue(session, settings, principal, metadata, upload: UploadSource):
    if not principal.admin:
        raise ApplicationError(403, "Document administration required")
    require_company(principal, metadata.company)
    try:
        pipeline = indexing_configuration(settings)
    except ValueError as exc:
        raise ApplicationError(503, str(exc)) from exc
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".pdf", ".md", ".txt"}:
        raise ApplicationError(415, "Supported sources: PDF, Markdown, UTF-8 text")
    # IDs are deterministic per administrator and import key, making upload retries safe.
    key = hashlib.sha256(f"{principal.subject}:{metadata.import_key}".encode()).hexdigest()
    file_name = Path((upload.filename or "source").replace("\\", "/")).name
    root = settings.storage_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    import tempfile

    digest, size = hashlib.sha256(), 0
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as file:
        temporary = Path(file.name)
        try:
            while data := await upload.read(65536):
                size += len(data)
                if size > settings.max_upload_bytes:
                    raise ApplicationError(413, "Source exceeds upload limit")
                digest.update(data)
                file.write(data)
            if not size:
                raise ApplicationError(422, "Source is empty")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    content_hash = digest.hexdigest()
    storage_key = content_hash + suffix
    target = source_path(settings, storage_key)
    temporary.replace(target)
    # Transaction-scoped lock serializes duplicate submissions across API processes.
    from sqlalchemy import text

    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(key[:15], 16)})
    existing = await session.get(DocumentVersion, key)
    signature = hashlib.sha256(
        json.dumps(
            {
                "metadata": metadata.model_dump(mode="json"),
                **pipeline,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if existing:
        if (
            existing.content_hash != content_hash
            or existing.pipeline.get("metadata_hash") != signature
        ):
            raise ApplicationError(409, "Import key already used for a different document")
        return await session.scalar(select(IngestionJob).where(IngestionJob.version_id == key))
    doc = None
    if metadata.document_id:
        doc = await session.get(Document, metadata.document_id)
        if not doc or doc.company not in principal.companies:
            raise ApplicationError(404, "Document not found")
        for field in ("company", "dept", "section", "doc_type", "year", "month", "meeting_date"):
            if getattr(doc, field) != getattr(metadata, field):
                raise ApplicationError(
                    409,
                    "Replacement must preserve document scope; import as a new document to change metadata",
                )
    if not doc:
        doc = Document(
            **metadata.model_dump(exclude={"document_id", "import_key"}), source_path=file_name
        )
        session.add(doc)
        await session.flush()
    version = DocumentVersion(
        id=key,
        doc_id=doc.doc_id,
        content_hash=content_hash,
        file_name=file_name,
        storage_key=storage_key,
        pipeline={"metadata_hash": signature, "requested": pipeline},
    )
    session.add(version)
    await session.flush()
    job = IngestionJob(version_id=key)
    session.add(job)
    await session.flush()
    return job


class DocumentService:
    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings

    async def upload(self, metadata, file, principal):
        async with self.sessions.begin() as session:
            job = await enqueue(session, self.settings, principal, metadata, file)
            return dict(job_id=job.id, version_id=job.version_id, status=job.status)

    async def reindex(self, doc_id, import_key, principal):
        if not principal.admin:
            raise ApplicationError(403, "Document administration required")
        async with self.sessions.begin() as session:
            doc = await session.get(Document, doc_id)
            if not doc or doc.company not in principal.companies or not doc.active_version_id:
                raise ApplicationError(404, "Active document not found")
            version = await session.get(DocumentVersion, doc.active_version_id)
            path = source_path(self.settings, version.storage_key)
            if not path.is_file():
                raise ApplicationError(409, "Retained source is missing; upload a replacement")
            metadata = DocumentMetadata(
                **{
                    key: getattr(doc, key)
                    for key in (
                        "company",
                        "dept",
                        "section",
                        "doc_type",
                        "year",
                        "month",
                        "meeting_date",
                    )
                },
                document_id=doc_id,
                import_key=import_key,
            )
            with path.open("rb") as file:
                job = await enqueue(
                    session,
                    self.settings,
                    principal,
                    metadata,
                    LocalUpload(file=file, filename=version.file_name),
                )
            return {"job_id": job.id, "version_id": job.version_id, "status": job.status}

    async def list(self, principal, offset=0):
        async with self.sessions() as session:
            docs = (
                await session.scalars(
                    select(Document)
                    .where(Document.company.in_(principal.companies))
                    .order_by(Document.created_at.desc(), Document.doc_id)
                    .offset(offset)
                    .limit(101)
                )
            ).all()
            return {
                "documents": [
                    {
                        "id": d.doc_id,
                        "company": d.company,
                        "dept": d.dept,
                        "year": d.year,
                        "month": d.month,
                        "active_version_id": d.active_version_id,
                    }
                    for d in docs[:100]
                ],
                "next_offset": offset + 100 if len(docs) > 100 else None,
            }

    async def source(self, doc_id, version_id, principal):
        async with self.sessions() as session:
            doc = await session.get(Document, doc_id)
            version = await session.get(DocumentVersion, version_id)
            if (
                not doc
                or doc.company not in principal.companies
                or not version
                or version.doc_id != doc_id
            ):
                raise ApplicationError(404, "Source not found")
            require_company(principal, doc.company)
            path = source_path(self.settings, version.storage_key)
            if not path.is_file():
                raise ApplicationError(404, "Retained source is unavailable")
            return SourceFile(path=path, filename=version.file_name)
