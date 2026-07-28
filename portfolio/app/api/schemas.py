from pydantic import BaseModel, ConfigDict, Field


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


class UploadResponse(BaseModel):
    tenant_id: str = Field(
        description="The tenant this document was ingested under, echoed for confirmation. Nothing needs "
        "to be passed back to /ask -- that call resolves the same tenant from your API key."
    )
    doc_id: str = Field(description="Content-hash-derived identifier assigned to the uploaded document")
    chunk_count: int = Field(description="Number of chunks the document was split into")
