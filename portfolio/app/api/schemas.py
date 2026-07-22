from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(description="The question to answer, grounded in the retrieved documents")
    session_id: str | None = Field(
        default=None,
        description="Omit to search only the curated corpus; pass an upload session's id to also "
        "search that session's own uploaded documents (never other sessions').",
    )


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
    session_id: str = Field(
        description="The session this document was ingested under -- pass it to /ask to query this document"
    )
    doc_id: str = Field(description="Content-hash-derived identifier assigned to the uploaded document")
    chunk_count: int = Field(description="Number of chunks the document was split into")
