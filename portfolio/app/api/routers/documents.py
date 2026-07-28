from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, File, UploadFile

# Runtime import on purpose -- see the note in ask.py: FastAPI resolves this annotation
# when registering the route, so a TYPE_CHECKING-only import breaks dependency injection.
from app.api.deps import CurrentTenant  # noqa: TC001
from app.api.schemas import UploadResponse
from app.config import get_settings
from app.exceptions import APIError
from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS, is_supported_upload
from app.ingestion.pipeline import ingest_document
from app.ingestion.uploads import safe_filename, tenant_upload_dir, upload_doc_id
from app.vectorstore.qdrant_store import QdrantStore

router = APIRouter()


@lru_cache
def _store() -> QdrantStore:
    return QdrantStore()


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

    # The path helpers are HTTP-agnostic (shared with the Streamlit UI, which builds the
    # same path in process), so their ValueError is translated here rather than there.
    try:
        tenant_dir = tenant_upload_dir(settings.upload_dir, tenant_id)
        filename = safe_filename(file.filename)
    except ValueError as exc:
        raise APIError(str(exc)) from exc

    tenant_dir.mkdir(parents=True, exist_ok=True)
    file_path = tenant_dir / filename
    file_path.write_bytes(file_bytes)

    chunk_count = await ingest_document(doc_id=doc_id, file_path=file_path, store=_store(), tenant_id=tenant_id)

    return UploadResponse(tenant_id=tenant_id, doc_id=doc_id, chunk_count=chunk_count)
