import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .database.connection import engine
from .database import models  # noqa: F401
from .database.schema_check import require_current_schema, schema_status
from . import config
from .api import router as api_router
from .auth_api import router as auth_router
from .corrections_api import router as corrections_router
from .import_api import router as import_router
from .security.body_limit import BodySizeLimitMiddleware
from .security.csrf import CSRFMiddleware
from .users_api import router as users_router


def check_production_settings() -> None:
    """In production, refuse to start without a usable backup directory."""
    if not config.IS_PRODUCTION:
        return

    if not config.BACKUP_DIR:
        raise RuntimeError(
            "COACHING_BACKUP_DIR must be set in production "
            "(safety backups before destructive operations)."
        )

    path = Path(config.BACKUP_DIR)
    if not path.is_dir() or not os.access(path, os.W_OK):
        raise RuntimeError(
            f"COACHING_BACKUP_DIR {path} is not a writable directory."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast if migrations have not been applied. The schema is never
    # created implicitly.
    require_current_schema(engine)
    check_production_settings()
    yield


app = FastAPI(
    title="Coaching Test Intelligence",
    version="0.1.0",
    lifespan=lifespan,
    # Interactive docs/OpenAPI schema are not served in production.
    docs_url="/docs" if config.API_DOCS_ENABLED else None,
    redoc_url="/redoc" if config.API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if config.API_DOCS_ENABLED else None,
)

# CORS is deliberately not enabled: the frontend is served from the same
# origin (Caddy in production, the Vite proxy in development).
app.add_middleware(CSRFMiddleware)
# Added last so it runs first: oversized bodies are refused before
# anything else reads them.
app.add_middleware(BodySizeLimitMiddleware)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(api_router)
app.include_router(corrections_router)
app.include_router(import_router)


@app.get("/")
def root():
    return {
        "application": "Coaching Test Intelligence",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/api/health")
def health():
    """
    Lightweight health check: runs a query and checks the schema
    revision. Returns 503 when the database is unusable.
    """

    status = schema_status(engine)

    if status != "ok":
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": status},
        )

    return {"status": "ok", "database": "ok"}
