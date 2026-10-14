from kyoritsu_backend.core.errors import ApplicationError
from kyoritsu_backend.db.models import Document, DocumentVersion, IngestionJob


class JobService:
    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings

    async def status(self, job_id, principal):
        async with self.sessions() as session:
            job = await session.get(IngestionJob, job_id)
            if not job:
                raise ApplicationError(404, "Job not found")
            version = await session.get(DocumentVersion, job.version_id)
            doc = await session.get(Document, version.doc_id)
            if doc.company not in principal.companies:
                raise ApplicationError(404, "Job not found")
            return {
                "id": job.id,
                "document_id": doc.doc_id,
                "version_id": version.id,
                "status": job.status,
                "attempts": job.attempts,
                "progress": job.progress,
                "error": job.error,
            }

    async def retry(self, job_id, principal):
        await self.status(job_id, principal)
        if not principal.admin:
            raise ApplicationError(403, "Administrator required")
        async with self.sessions.begin() as session:
            job = await session.get(IngestionJob, job_id, with_for_update=True)
            if job.status != "failed" or job.attempts >= self.settings.max_job_attempts:
                raise ApplicationError(409, "Job is not retryable or attempt limit reached")
            job.status, job.error = "queued", None
            (await session.get(DocumentVersion, job.version_id)).status = "queued"
        return await self.status(job_id, principal)
