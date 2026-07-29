from datetime import datetime  # noqa: TC003 -- see below

from pydantic import BaseModel, ConfigDict, Field

# `datetime` must stay a runtime import. This module has no `from __future__ import
# annotations`, so pydantic evaluates these annotations eagerly when it builds the model
# classes; moving it into a TYPE_CHECKING block (as ruff's TC003 suggests) makes
# DocumentStatusResponse fail at import with an unresolvable `datetime` name.


class AskRequest(BaseModel):
    """Carries no tenant/session field, by design.

    Retrieval scope comes from the `x-api-key` header via `api/deps.py::current_tenant`. An
    earlier version accepted `session_id` here, which let any caller read another tenant's
    documents just by passing their id. `extra="forbid"` makes a request that still sends
    one fail with a 422 rather than being silently ignored -- a stale client is told plainly
    instead of quietly getting corpus-only results.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="The question to answer, grounded in the retrieved documents")


class CitationResponse(BaseModel):
    quoted_text: str = Field(description="The exact source text the answer is grounded in")
    chunk_id: str = Field(description="Identifier of the specific chunk this citation points to")
    doc_id: str = Field(description="Identifier of the document the cited chunk belongs to")
    page_no: int | None = Field(description="Page number the citation was found on, if known")


class RetrievedChunkResponse(BaseModel):
    chunk_id: str = Field(description="Identifier of this chunk")
    doc_id: str = Field(description="Identifier of the document this chunk belongs to")
    chunk_type: str = Field(description='Kind of content this chunk holds -- "text", "table", or "figure"')
    page_no: int | None = Field(description="Page number this chunk was found on, if known")
    section_path: str = Field(description="Section heading path within the document, if available")
    text: str = Field(description="The chunk's content (prose, a serialized table, or a figure caption)")


class AskResponse(BaseModel):
    answer: str = Field(description="The generated answer text")
    citations: list[CitationResponse] = Field(description="Sources the answer explicitly cites")
    retrieved_chunks: list[RetrievedChunkResponse] = Field(
        description="Every chunk retrieved and reranked for this question, cited or not"
    )


class UploadAcceptedResponse(BaseModel):
    """The 202 from `POST /v1/documents`.

    Replaces an earlier `UploadResponse` that returned `chunk_count`, which is a **breaking
    change** and unavoidable: ingestion now happens in a background worker, so at the moment
    this response is written the document has not been parsed and no chunk count exists.
    Returning a placeholder 0 would have kept the shape and lied. Poll
    `GET /v1/documents/{doc_id}` for the count.
    """

    tenant_id: str = Field(
        description="The tenant this document was accepted under, echoed for confirmation. Nothing needs "
        "to be passed back to /ask -- that call resolves the same tenant from your API key."
    )
    doc_id: str = Field(description="Content-hash-derived identifier assigned to the uploaded document")
    status: str = Field(description='Always "pending" here -- the job is queued, not yet started')


class DocumentStatusResponse(BaseModel):
    """`GET /v1/documents/{doc_id}`. The other half of the async upload contract: without a
    way to read status, a client cannot tell a queued document from a failed one.
    """

    doc_id: str = Field(description="Identifier of the document")
    tenant_id: str = Field(description="The tenant that owns this document")
    filename: str = Field(description="Original filename as uploaded")
    status: str = Field(description='"pending", "processing", "ingested", or "failed"')
    chunk_count: int = Field(description="Chunks produced. 0 until ingestion succeeds")
    error_message: str | None = Field(
        description='Why ingestion failed, when status is "failed". Cleared if a retry succeeds'
    )
    uploaded_at: datetime | None = Field(description="When the document was first accepted")
    updated_at: datetime | None = Field(
        description="When the status last changed. A 'processing' status with an old timestamp means a "
        "worker died mid-job rather than that work is still in progress"
    )
