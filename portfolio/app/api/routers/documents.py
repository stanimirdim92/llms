import uuid
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from app.api.schemas import UploadResponse
from app.config import get_settings
from app.exceptions import APIError
from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS, is_supported_upload
from app.ingestion.pipeline import ingest_document
from app.ingestion.uploads import upload_doc_id
from app.vectorstore.qdrant_store import QdrantStore

router = APIRouter()


@lru_cache
def _store() -> QdrantStore:
    return QdrantStore()


@router.post(
    "/documents",
    response_model=UploadResponse,
    tags=["documents"],
    summary="Upload a document into a session's own searchable scope",
    description="Ingests the file (parse, chunk, embed, store) and tags every chunk with `session_id` so "
    "it's only searchable by /ask calls passing that same session_id, never by other sessions.",
    response_description="The session/document ids to use with /ask, plus how many chunks were produced",
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    session_id: Annotated[str | None, Form()] = None,
) -> UploadResponse:
    if not file.filename or not is_supported_upload(file.filename):
        raise APIError(f"Unsupported file type. Supported extensions: {sorted(SUPPORTED_UPLOAD_EXTENSIONS)}")

    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    file_bytes = await file.read()
    if len(file_bytes) > max_bytes:
        raise APIError(f"File exceeds the {settings.max_upload_size_mb}MB limit", code=413)

    session_id = session_id or uuid.uuid7().hex
    doc_id = upload_doc_id(session_id, file_bytes)

    session_dir = settings.upload_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    file_path = session_dir / file.filename
    file_path.write_bytes(file_bytes)

    chunk_count = await ingest_document(doc_id=doc_id, file_path=file_path, store=_store(), session_id=session_id)

    return UploadResponse(session_id=session_id, doc_id=doc_id, chunk_count=chunk_count)
