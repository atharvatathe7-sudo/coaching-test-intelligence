"""
Serve the built React app (frontend/dist) from FastAPI.

Used in local mode so no separate web server is needed. API routes are
untouched: only a request that would otherwise be a 404 is considered,
and /api/* paths keep their JSON 404. Missing files with an extension
(for example /assets/old.js) stay 404 rather than returning the app, so
a stale asset reference fails visibly.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

NO_CACHE = {"Cache-Control": "no-cache"}
# Vite writes content-hashed names into assets/, so they never change.
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


class FrontendMissing(RuntimeError):
    pass


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def install_frontend(app: FastAPI, dist: Path) -> None:
    dist = Path(dist).resolve()
    index = dist / "index.html"

    if not index.is_file():
        raise FrontendMissing(
            f"The built frontend was not found at {dist}. "
            "Run `npm run build` in the frontend folder first."
        )

    def index_response() -> FileResponse:
        return FileResponse(index, headers=NO_CACHE)

    @app.get("/", include_in_schema=False)
    def frontend_root():
        return index_response()

    @app.exception_handler(StarletteHTTPException)
    async def fallback(request: Request, exc: StarletteHTTPException):
        path = request.url.path

        if (
            exc.status_code != 404
            or request.method not in ("GET", "HEAD")
            or _is_api_path(path)
        ):
            return await http_exception_handler(request, exc)

        relative = path.lstrip("/")
        candidate = (dist / relative).resolve()

        if candidate.is_file() and candidate.is_relative_to(dist):
            headers = IMMUTABLE if relative.startswith("assets/") else NO_CACHE
            return FileResponse(candidate, headers=headers)

        if "." in Path(relative).name:
            return await http_exception_handler(request, exc)

        return index_response()
