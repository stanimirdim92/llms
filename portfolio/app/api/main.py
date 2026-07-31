# FastAPI reads lifespan's return annotation at runtime, so this import must not move
# into a TYPE_CHECKING block.
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers.ask import router as ask_router
from app.api.routers.documents import router as documents_router
from app.api.routers.health import router as health_router
from app.config import get_settings, require_provider_credentials
from app.db import init_db
from app.exceptions import PortfolioError
from app.logs import configure_logging

configure_logging()
log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Check credentials and create tables before serving.

    Credentials first, and it refuses to start without them rather than logging a warning.
    Every `/ask` and every ingest needs Anthropic and Voyage, so a container missing them can
    serve nothing -- but it would still pass a health check, accept uploads, and fail each one
    individually somewhere inside an HTTP call. Failing at boot puts the reason in the first
    lines of `docker compose logs api` instead.

    Without `init_db`, the first authenticated request queries `api_keys` on a database where
    it may not exist yet, and a missing table surfaces as a 500 that looks nothing like the
    auth problem it resembles. `init_db` is guarded internally, so this stays a single DDL
    round-trip per process rather than one per request.
    """
    require_provider_credentials()
    await init_db()
    log.info("api.started")
    yield


app = FastAPI(
    title="AI Engineer Portfolio — Track",
    version="0.1.0",
    description="RAG over scientific/technical documents with forced citations",
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
    lifespan=lifespan,
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_allow_origins,
    allow_methods=_settings.cors_allow_methods,
    allow_headers=_settings.cors_allow_headers,
    expose_headers=_settings.cors_expose_headers,
    # Settings refuses to construct if this is on alongside wildcard origins -- see
    # config.py::_reject_credentialed_wildcard_cors for what Starlette does with that
    # pair and why it can't be left to a warning.
    allow_credentials=_settings.cors_allow_credentials,
)

# No /v1 prefix: probes are infrastructure, not API surface. Versioning them would mean an
# orchestrator's health check breaking when the API version moves, which is backwards.
app.include_router(health_router)
app.include_router(ask_router, prefix="/v1")
app.include_router(documents_router, prefix="/v1")


@app.exception_handler(PortfolioError)
async def portfolio_error_handler(request: Request, exc: PortfolioError) -> JSONResponse:
    # FastAPI's default HTTPException handler already produces this exact response
    # shape; this handler only adds structured logging on top of that, so a raised
    # APIError still shows up in the same place as everything else structlog captures.
    #
    # `headers=exc.headers` is not optional decoration: overriding the default handler means
    # this one is now solely responsible for anything the default would have forwarded, and
    # dropping them silently discards `Retry-After` on a 429 -- the response would tell a
    # client to back off without saying for how long.
    log.warning("api.error", path=request.url.path, status_code=exc.status_code, detail=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


@app.get("/")
async def root() -> dict:
    return {"message": "AI Engineer Portfolio API"}
