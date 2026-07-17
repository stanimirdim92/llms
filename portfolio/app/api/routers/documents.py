import uuid
from functools import lru_cache

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.schemas import UploadResponse
from app.config import get_settings
from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS, is_supported_upload
from app.ingestion.pipeline import ingest_document
from app.ingestion.uploads import upload_doc_id
from app.vectorstore.chroma_store import ChromaStore

router = APIRouter()


@lru_cache
def _store() -> ChromaStore:
    return ChromaStore()


@router.post("/documents", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...), session_id: str | None = Form(None)) -> UploadResponse:
    if not file.filename or not is_supported_upload(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported extensions: {sorted(SUPPORTED_UPLOAD_EXTENSIONS)}",
        )

    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    file_bytes = await file.read()
    if len(file_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds the {settings.max_upload_size_mb}MB limit")

    session_id = session_id or uuid.uuid4().hex
    doc_id = upload_doc_id(session_id, file_bytes)

    session_dir = settings.upload_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    file_path = session_dir / file.filename
    file_path.write_bytes(file_bytes)

    chunk_count = ingest_document(doc_id=doc_id, file_path=file_path, store=_store(), session_id=session_id)

    return UploadResponse(session_id=session_id, doc_id=doc_id, chunk_count=chunk_count)
