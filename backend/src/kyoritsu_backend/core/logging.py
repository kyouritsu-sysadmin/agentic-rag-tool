import json
import logging
from uuid import uuid4
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def request_id(request, call_next):
    request.state.request_id = str(uuid4())
    if request.url.path.startswith("/v1/") and not await request.app.state.ownership.check():
        response = JSONResponse(
            status_code=503, content={"detail": "API ownership lost; restart this process"}
        )
    else:
        response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    logger.info(
        json.dumps(
            {
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
            }
        )
    )
    return response
