import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, UploadFile

# Runtime import on purpose -- see the note in ask.py: FastAPI resolves this annotation
# when registering the route, so a TYPE_CHECKING-only import breaks dependency injection.
from app.api.deps import CurrentTenant  # noqa: TC001
from app.api.schemas import UploadResponse
from app.auth.models import TENANT_ID_PATTERN
from app.config import get_settings
from app.exceptions import APIError
from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS, is_supported_upload
from app.ingestion.pipeline import ingest_document
from app.ingestion.uploads import upload_doc_id
from app.vectorstore.qdrant_store import QdrantStore

router = APIRouter()

_TENANT_ID_RE = re.compile(TENANT_ID_PATTERN)


@lru_cache
def _store() -> QdrantStore:
    return QdrantStore()


def _safe_filename(filename: str | None) -> str:
    """Reduce a client-supplied filename to a bare name safe to join onto a directory.

    `UploadFile.filename` is whatever the client sent, so it may contain path separators or
    `..`. Without this, `session_dir / filename` escapes the upload directory and the write
    lands wherever the client chose -- an arbitrary file write. `Path(...).name` discards any
    directory portion; the remaining checks reject names that are still not usable.
    """
    candidate = Path(filename or "").name
    if not candidate or candidate.startswith("."):
        raise APIError("File must have a usable, non-hidden filename")
    return candidate


def _tenant_upload_dir(tenant_id: str) -> Path:
    """The tenant's own upload directory, verified to be inside the configured root.

    `tenant_id` is server-generated (`uuid7().hex`) and never client-supplied, so the format
    check is belt and braces -- but a path built from an identifier should not depend on that
    guarantee holding forever, and the containment assert catches any future mistake in how
    this path is composed rather than trusting it.
    """
    if not _TENANT_ID_RE.fullmatch(tenant_id):
        raise APIError("Authenticated tenant id has an unexpected format", code=500)

    root = get_settings().upload_dir.resolve()
    directory = (root / tenant_id).resolve()
    if not directory.is_relative_to(root):
        raise APIError("Refusing to write outside the upload directory", code=500)
    return directory


@router.post(
    "/documents",
    response_model=UploadResponse,
    tags=["documents"],
    summary="Upload a document into the authenticated tenant's searchable scope",
    description="Ingests the file (parse, chunk, embed, store) and tags every chunk with the tenant "
    "the `x-api-key` header authenticates as, so only that tenant's /ask calls can retrieve it. "
    "Requires a valid API key.",
    response_description="The tenant/document ids and how many chunks were produced",
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    tenant_id: CurrentTenant,
) -> UploadResponse:
    if not file.filename or not is_supported_upload(file.filename):
        raise APIError(f"Unsupported file type. Supported extensions: {sorted(SUPPORTED_UPLOAD_EXTENSIONS)}")

    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    # NOTE: reads the whole body before checking its size, so max_upload_size_mb bounds what
    # is *stored*, not what is buffered in memory. Streaming to disk with an incremental
    # size check is tracked as EPIC_4_PLAN.md 1.6 and deliberately not bundled here.
    file_bytes = await file.read()
    if len(file_bytes) > max_bytes:
        raise APIError(f"File exceeds the {settings.max_upload_size_mb}MB limit", code=413)

    doc_id = upload_doc_id(tenant_id, file_bytes)

    tenant_dir = _tenant_upload_dir(tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    file_path = tenant_dir / _safe_filename(file.filename)
    file_path.write_bytes(file_bytes)

    chunk_count = await ingest_document(doc_id=doc_id, file_path=file_path, store=_store(), tenant_id=tenant_id)

    return UploadResponse(tenant_id=tenant_id, doc_id=doc_id, chunk_count=chunk_count)
