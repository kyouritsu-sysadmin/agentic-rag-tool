from .api.routes import router
from .api.exceptions import application_error, unexpected
from .core.errors import ApplicationError
from .core.logging import request_id
from .services.recovery import interrupt_orphaned_runs
from .services.threads import ThreadService
from .services.runs import RunService
from .services.documents import DocumentService
from .services.jobs import JobService
from .services.models import ModelCatalog
import asyncio
import logging
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from .core.settings import Settings
from .core.body_limit import BodyLimit
from .core.ownership import ApiOwnership

from .db.session import create_database
from .db.models import Thread

from .providers.models import ModelProvider
from .services.retrieval import RetrievalService
from .services.chat import ChatService

logger = logging.getLogger(__name__)


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        engine, sessions = create_database(settings.database_url.get_secret_value())
        app.state.sessions = sessions
        app.state.models = ModelProvider(settings)
        app.state.retrieval = RetrievalService(sessions, app.state.models, settings)
        app.state.chat = ChatService(sessions, app.state.retrieval, settings)
        app.state.threads = ThreadService(sessions)
        app.state.runs = RunService(sessions, chat=app.state.chat)
        app.state.documents = DocumentService(sessions, settings)
        app.state.jobs = JobService(sessions, settings)
        app.state.catalog = ModelCatalog(app.state.models, settings)
        owner = app.state.ownership = ApiOwnership(engine)
        monitor = None
        try:
            await owner.acquire()
            owner.fence_sessions(sessions)
            await interrupt_orphaned_runs(sessions)
            monitor = asyncio.create_task(owner.monitor(app.state.chat))
            yield
        finally:
            if monitor:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            try:
                await app.state.chat.close()
            finally:
                try:
                    await app.state.models.close()
                finally:
                    try:
                        await owner.close()
                    finally:
                        await engine.dispose()

    app = FastAPI(title="Kyoritsu RAG", version="1.0.1", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(BodyLimit, limit=settings.max_upload_bytes + 65536)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID"],
    )

    app.middleware("http")(request_id)
    app.add_exception_handler(ApplicationError, application_error)
    app.add_exception_handler(Exception, unexpected)
    app.include_router(router)

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        checks = {
            "ownership": await app.state.ownership.check(),
            "database": False,
            "models": app.state.models.loaded,
            "answer_provider": False,
        }
        try:
            async with app.state.sessions() as session:
                await session.execute(select(Thread.id).limit(1))
            checks["database"] = True
            if settings.model_backend == "test":
                checks["answer_provider"] = True
            else:
                async with httpx.AsyncClient(timeout=3) as client:
                    response = await client.get(settings.ollama_url.rstrip("/") + "/api/tags")
                    response.raise_for_status()
                    checks["answer_provider"] = any(
                        m["name"] == settings.answer_model
                        for m in response.json().get("models", [])
                    )
        except Exception:
            pass
        return JSONResponse(status_code=200 if all(checks.values()) else 503, content=checks)

    return app
