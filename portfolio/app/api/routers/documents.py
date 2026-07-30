from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

# Runtime import on purpose -- see the note in ask.py: FastAPI resolves these annotations
# when registering the route, so a TYPE_CHECKING-only import breaks dependency injection.
from app.api.deps import CurrentTenant, rate_limited
from app.api.schemas import DocumentStatusResponse, UploadAcceptedResponse
from app.config import get_settings
from app.db import get_session, init_db
from app.exceptions import APIError
from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS, is_supported_upload
from app.ingestion.uploads import safe_filename, tenant_upload_dir, upload_doc_id
from app.registry.db import get_document_record, stage_document_record
from app.registry.models import STATUS_PENDING, DocumentRecord
from app.worker.app import defer_document_ingest

router = APIRouter()


@router.post(
    "/documents",
    response_model=UploadAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["documents"],
    summary="Queue a document for ingestion into the authenticated tenant's searchable scope",
    description="Stores the file and queues parse/chunk/embed as a background job, returning immediately. "
    "Every chunk is tagged with the tenant the `x-api-key` header authenticates as, so only that tenant's "
    "/ask calls can retrieve it. Poll GET /v1/documents/{doc_id} for progress. Requires a valid API key.",
    response_description="The tenant/document ids and the queued status",
    dependencies=[Depends(rate_limited("upload", "rate_limit_upload"))],
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    tenant_id: CurrentTenant,
) -> UploadAcceptedResponse:
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
    # Written before the transaction below, and the ordering is deliberate: the worker is a
    # separate process that reads this path, so the file has to exist by the time the job
    # becomes visible. The reverse order gives a job that reliably fails on a missing file.
    # The cost of this direction is an orphaned file if the transaction rolls back, which is
    # harmless -- `doc_id` is a content hash, so a re-upload lands on the same path and
    # overwrites it.
    file_path.write_bytes(file_bytes)

    await init_db()
    record = DocumentRecord(
        doc_id=doc_id,
        tenant_id=tenant_id,
        filename=filename,
        content_hash=doc_id,
        file_extension=file_path.suffix,
        file_size_bytes=len(file_bytes),
        status=STATUS_PENDING,
    )

    # One transaction for both writes: the row and its job commit together or not at all.
    # See defer_document_ingest's docstring for the two silent failure windows that closes.
    async with get_session() as session:
        await stage_document_record(session, record)
        await defer_document_ingest(session, doc_id=doc_id, tenant_id=tenant_id, file_path=str(file_path))
        await session.commit()

    return UploadAcceptedResponse(tenant_id=tenant_id, doc_id=doc_id, status=STATUS_PENDING)


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentStatusResponse,
    tags=["documents"],
    summary="Check ingestion progress for one of your documents",
    description="Reports whether a queued document is still pending, being processed, finished, or failed "
    "(with the reason). Only returns documents owned by the tenant the `x-api-key` header authenticates as.",
    response_description="The document's current ingestion status",
    dependencies=[Depends(rate_limited("ask", "rate_limit_ask"))],
)
async def get_document_status(doc_id: str, tenant_id: CurrentTenant) -> DocumentStatusResponse:
    await init_db()
    async with get_session() as session:
        record = await get_document_record(session, tenant_id=tenant_id, doc_id=doc_id)

    # 404 rather than 403 for another tenant's document, deliberately. `doc_id` is a content
    # hash, so answering "exists but not yours" would confirm to any caller that a given file
    # has been uploaded by *somebody* -- an existence oracle over content.
    if record is None:
        raise APIError("Document not found", code=404)

    return DocumentStatusResponse(
        doc_id=record.doc_id,
        tenant_id=record.tenant_id,
        filename=record.filename,
        status=record.status,
        chunk_count=record.chunk_count,
        error_message=record.error_message,
        uploaded_at=record.uploaded_at,
        updated_at=record.updated_at,
    )
