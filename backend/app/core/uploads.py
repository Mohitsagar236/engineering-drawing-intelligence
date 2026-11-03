from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from app.core.config import settings


class UploadBodyLimit:
    """Limit bytes before multipart parsing can spool an oversized request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path")
            not in ("/api/documents", "/api/documents/upload", "/api/materials/import")
        ):
            return await self.app(scope, receive, send)
        limit = (
            2 if scope["path"] == "/api/materials/import" else settings.max_upload_mb
        ) * 1024 * 1024 + 128 * 1024
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse(
                {"detail": "Invalid Content-Length"}, status_code=400
            )(scope, receive, send)
        if length > limit:
            return await JSONResponse(
                {"detail": "Request body exceeds upload limit"}, status_code=413
            )(scope, receive, send)
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > limit:
                raise HTTPException(413, "Request body exceeds upload limit")
            return message

        await self.app(scope, bounded_receive, send)
