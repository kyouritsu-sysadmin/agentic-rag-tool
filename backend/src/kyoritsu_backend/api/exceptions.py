import logging
from fastapi.responses import JSONResponse
from kyoritsu_backend.core.errors import ApplicationError

logger = logging.getLogger(__name__)


async def application_error(request, exc: ApplicationError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


async def unexpected(request, exc):
    request_id = getattr(request.state, "request_id", None)
    logger.error("Unhandled request error: %s", request_id, exc_info=exc)
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error", "request_id": request_id}
    )
