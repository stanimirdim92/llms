from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None
    """Omit to search only the curated corpus; pass an upload session's id to also
    search that session's own uploaded documents (never other sessions')."""


class CitationResponse(BaseModel):
    quoted_text: str
    chunk_id: str
    doc_id: str
    page_no: int | None


class RetrievedChunkResponse(BaseModel):
    chunk_id: str
    doc_id: str
    chunk_type: str
    page_no: int | None
    section_path: str
    text: str


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    retrieved_chunks: list[RetrievedChunkResponse]


class UploadResponse(BaseModel):
    session_id: str
    doc_id: str
    chunk_count: int
