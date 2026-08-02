from datetime import datetime  # see the note below: must stay a runtime import
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.auth.expiry import DEFAULT_EXPIRY_DAYS

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
    scoped_to: list[str] = Field(
        default_factory=list,
        description="Filenames the search was restricted to, because the question named them. "
        "Empty means the whole corpus plus all of this tenant's uploads were searched. Present so "
        "narrowing is never silent -- an answer drawn from one document reads identically to one "
        "drawn from everything.",
    )
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


class DocumentListResponse(BaseModel):
    """`GET /v1/documents`. The answer to "what documents do I have?", which cannot come from
    /ask: retrieval matches chunks semantically, so a meta-question about the corpus gets grounded
    in whatever text happens to be nearest in embedding space.
    """

    documents: list[DocumentStatusResponse] = Field(description="This tenant's documents, newest first")
    count: int = Field(description="How many are returned (bounded by `limit`)")


class CreateKeyRequest(BaseModel):
    """`POST /v1/keys`. Carries no tenant field for the same reason `AskRequest` doesn't --
    the tenant comes from the calling key, never from the body.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=64,
        description='Human label for the key ("ci", "laptop"). Once minted, this and the prefix are '
        "the only way to tell one key from another -- the secret itself is unrecoverable.",
    )
    scopes: list[str] = Field(
        default_factory=list,
        description="What the new key may do. Empty means *the same scopes you hold*, which for an "
        "unrestricted key is everything. You can never grant a scope your own key lacks; trying "
        "returns 403.",
    )
    expires_in_days: Literal[30, 60, 90, 365] | None = Field(
        default=DEFAULT_EXPIRY_DAYS,
        description="Lifetime in days. `null` means the key never expires -- allowed, but say it "
        "explicitly rather than getting it by omission, which is why the default is 30 rather than "
        "no deadline.",
    )


class ApiKeyResponse(BaseModel):
    """A key's metadata. Deliberately cannot carry the secret: `CreatedKeyResponse` adds that
    field exactly once, on the one response that is allowed to show it.
    """

    key_id: str = Field(description="Identifier for this key -- what `DELETE /v1/keys/{key_id}` takes")
    name: str = Field(description="The label given at creation")
    prefix: str = Field(description="The key's first few characters, enough to recognise it in a list")
    scopes: list[str] = Field(
        description="What this key may do. An unrestricted key reports the full scope list rather than "
        "an empty one, so a client never has to know that empty means everything."
    )
    created_at: datetime | None = Field(description="When the key was minted")
    expires_at: datetime | None = Field(description="When it stops working on its own. `null` means never")
    last_used_at: datetime | None = Field(
        description="Last authenticated request, accurate to about a minute -- it is refreshed at most "
        "once per minute per key rather than on every call"
    )
    revoked_at: datetime | None = Field(description="When someone killed it. `null` means it was not revoked")


class CreatedKeyResponse(ApiKeyResponse):
    """The 201 from `POST /v1/keys`, and the only place the plaintext ever appears."""

    key: str = Field(
        description="The key itself, shown **once**. Only its hash is stored, so this response cannot "
        "be reproduced -- a lost key is revoked and replaced."
    )
