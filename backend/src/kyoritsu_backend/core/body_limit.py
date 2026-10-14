from fastapi import HTTPException
from starlette.responses import JSONResponse


class BodyLimit:
    """Bound actual bytes, including multipart spooling and chunked requests."""

    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(
                scope, receive, send
            )
        if declared > self.limit:
            return await JSONResponse({"detail": "Request exceeds upload limit"}, status_code=413)(
                scope, receive, send
            )
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > self.limit:
                raise HTTPException(413, "Request exceeds upload limit")
            return message

        await self.app(scope, bounded_receive, send)
