"""Liveness and readiness, kept separate because they answer different questions.

The endpoint this replaces was `GET /` returning a static dict. That is what the container
`HEALTHCHECK` curled and therefore what `depends_on: service_healthy` and nginx trusted -- so
the stack reported healthy with Postgres down, Qdrant unreachable and Redis gone. Every
dependency outage looked like a working container returning 500s.

The split matters more than it looks:

- **Liveness** asks "is this process wedged?" and must NOT check dependencies. A liveness probe
  that fails during a Postgres blip gets the process killed and restarted, which fixes nothing
  and turns a database hiccup into a restart storm.
- **Readiness** asks "can this instance serve a request right now?" and must check them.

Neither is authenticated or rate-limited: a probe that needs an API key is useless to an
orchestrator, and one that can be throttled reports unhealthy under load, which is exactly
when a truthful answer matters.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

import structlog
from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text

from app import rate_limit
from app.config import get_settings
from app.db import get_engine

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

router = APIRouter()
log = structlog.get_logger(__name__)

# How long a single dependency probe may take before it counts as down. Deliberately short:
# a readiness check that hangs is worse than one that reports "not ready", because the caller
# has no answer at all and its own timeout decides.
_PROBE_TIMEOUT_SECONDS = 3.0


class DependencyStatus(BaseModel):
    status: Literal["ok", "down"] = Field(description="Whether this dependency answered")
    required: bool = Field(description="Whether the API can serve requests without it")
    detail: str | None = Field(default=None, description="Error summary when down")


class ReadinessResponse(BaseModel):
    ready: bool = Field(description="False when any *required* dependency is down")
    dependencies: dict[str, DependencyStatus] = Field(description="Per-dependency probe results")


async def _probe_postgres() -> None:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


@lru_cache
def _qdrant_probe_client() -> AsyncQdrantClient:
    """A bare client, deliberately not `QdrantStore`.

    `QdrantStore.__init__` goes through `QdrantVectorStore.construct_instance`, which sends a
    **throwaway probe embedding** to detect the vector dimension. Using it here would bill a
    Voyage API call on every health check -- roughly 2,900 a day at the 30s `HEALTHCHECK`
    interval -- and would report Qdrant as down whenever *Voyage* was down, which is the wrong
    answer to the question being asked.

    Cached so the probe reuses one connection instead of opening one every 30 seconds.
    """
    return AsyncQdrantClient(url=get_settings().qdrant_url)


async def _probe_qdrant() -> None:
    # `get_collections` rather than counting points in our collection: it answers "is Qdrant
    # reachable and responding" without depending on the collection already existing, so a
    # fresh deployment reports ready before the first ingest rather than after it.
    await _qdrant_probe_client().get_collections()


async def _probe_redis() -> None:
    # The module-private per-loop client on purpose: that cached instance, bound to this event
    # loop, is exactly what the limiter will use, so probing anything else could report healthy
    # while the client the limiter holds is broken.
    await rate_limit._client().ping()


async def _run_probe(
    name: str, probe: Callable[[], Awaitable[None]], *, required: bool
) -> tuple[str, DependencyStatus]:
    try:
        await asyncio.wait_for(probe(), timeout=_PROBE_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 -- any failure means "down"; the type is for the detail
        log.warning("health.dependency_down", dependency=name, error=str(exc))
        return name, DependencyStatus(status="down", required=required, detail=f"{type(exc).__name__}: {exc}")
    return name, DependencyStatus(status="ok", required=required)


@router.get(
    "/health/live",
    tags=["health"],
    summary="Liveness -- is the process running?",
    description="Always 200 if the process can answer at all. Deliberately checks no "
    "dependencies: a liveness probe that fails on a database blip causes a restart loop that "
    "fixes nothing.",
    response_description="A static acknowledgement",
)
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    tags=["health"],
    summary="Readiness -- can this instance serve a request?",
    description="Probes Postgres, Qdrant and Redis concurrently. Returns 503 when a *required* "
    "dependency is down. Redis is reported but not required: rate limiting fails open, so its "
    "outage degrades a guardrail rather than the API.",
    response_description="Per-dependency results; 503 if any required one is down",
)
async def ready(response: Response) -> ReadinessResponse:
    # Concurrently, so readiness costs one timeout rather than three in series.
    results = await asyncio.gather(
        _run_probe("postgres", _probe_postgres, required=True),
        _run_probe("qdrant", _probe_qdrant, required=True),
        _run_probe("redis", _probe_redis, required=False),
    )
    dependencies = dict(results)

    # Postgres and Qdrant are required because nothing works without them: no auth lookup means
    # every request is a 401, and no vector store means /ask has nothing to retrieve. Redis only
    # backs rate limiting, which fails open by design -- reporting it keeps the outage visible
    # without pretending the API is unusable.
    is_ready = all(dep.status == "ok" for dep in dependencies.values() if dep.required)
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(ready=is_ready, dependencies=dependencies)
