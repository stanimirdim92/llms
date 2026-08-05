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
from app.api.routers.keys import router as keys_router
from app.config import get_settings, require_provider_credentials, require_reranker_backend
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
    # Same fail-fast reasoning one layer along: RERANKER_BACKEND=local with the extra
    # missing boots fine, passes readiness, and then fails every /ask.
    require_reranker_backend()
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
app.include_router(keys_router, prefix="/v1")


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
    # `rate_limited` sets X-RateLimit-* on the route's sub-response, which never materialises
    # on an error path -- this handler builds its own response. Re-attached here so a 404 or a
    # 422 advertises the same budget a 200 does; `exc.headers` wins on a 429, which carries
    # its own copy alongside Retry-After.
    headers = {**getattr(request.state, "ratelimit_headers", {}), **(exc.headers or {})}
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers or None)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Everything that is not already an `APIError`.

    Without this, an unanticipated exception -- a provider SDK raising something new, a
    `KeyError` off chunk metadata, a Postgres `IntegrityError`, an outright bug -- escapes
    every route and is answered by Starlette's `ServerErrorMiddleware` with a bare
    `PlainTextResponse("Internal Server Error")`. Two things break at once, and both are silent:

    1. It never reaches the structured `api.error` log above, so there is no server-side
       trace of the one category of failure most worth tracing. That is rule 7 inverted.
    2. It breaks the `{"detail": ...}` contract every other error in this API honours,
       including FastAPI's own defaults -- a client's error handling has to special-case it.
    **What it does not fix, stated because the obvious guess is wrong:** a 500 still carries no
    CORS headers. Registering a handler for bare `Exception` does not put it inside
    `CORSMiddleware` -- Starlette lifts it out of `ExceptionMiddleware` and installs it *as*
    `ServerErrorMiddleware`'s handler (`starlette/applications.py`), which is the outermost
    layer. Measured on this app: an unhandled error returns `access-control-allow-origin:
    None` while a 401 on the same app returns `*`. A browser client therefore still sees an
    opaque network error on a 500, and making that a real CORS response needs middleware
    *inside* `CORSMiddleware`, not an exception handler.

    `exc_info=exc` so the traceback is captured, and the response body deliberately says
    nothing about `exc` -- an unanticipated exception's message is exactly the kind of thing
    that leaks a connection string or a file path.

    Registering a handler for bare `Exception` is honoured by Starlette but does **not**
    catch anything raised inside a background task or after the response has started
    streaming; those still land in `ServerErrorMiddleware`.
    """
    log.exception("api.unhandled", path=request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
