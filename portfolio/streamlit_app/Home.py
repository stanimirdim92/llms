"""Demo UI for the /ask RAG pipeline: upload your own documents, ask a question, get a
cited answer grounded in the documents your tenant has uploaded.

This UI calls the ingestion and answer code *in process* rather than over HTTP, so
`api/deps.py::current_tenant` never runs for it. It therefore has to authenticate itself:
it asks for an API key and resolves it through `auth.service.resolve_tenant` -- the same
function the API dependency uses, so there is one auth implementation rather than two. It
must not mint its own tenant id; that would be exactly the "client chooses its own scope"
hole the API just closed.
"""

import asyncio

import streamlit as st

from app.auth.service import resolve_tenant
from app.config import get_settings
from app.db import get_session, init_db
from app.generation.answer_service import AnswerService
from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS, is_supported_upload
from app.ingestion.pipeline import EmptyDocumentError, ingest_document
from app.ingestion.uploads import content_digest, document_upload_path, upload_doc_id, write_upload
from app.logs import configure_logging
from app.registry.db import list_document_records, stage_document_record

# Runtime import, not TYPE_CHECKING. This module has no `from __future__ import
# annotations`, so `-> list[DocumentRecord]` on `_list_documents` is evaluated when the
# function is defined: under a TYPE_CHECKING-only import that raises NameError at import
# time and Streamlit never starts. Same trap as `datetime` in the model modules -- see
# CLAUDE.md's failure contracts. ruff only catches it when target-version is the real
# floor (py313); on py314 PEP 649 defers the annotation and the bug is invisible.
from app.registry.models import STATUS_PENDING, DocumentRecord
from app.retrieval.document_scope import DocumentScope, mentions_a_document, resolve_scope
from app.vectorstore.qdrant_store import QdrantStore

configure_logging()

st.set_page_config(page_title="AI Engineer Portfolio — RAG Demo", page_icon="📄")
st.title("Scientific Document RAG")
st.caption("Upload a document, then ask questions about it. Nothing is searchable until you upload something.")

if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = None
if "uploaded_docs" not in st.session_state:
    st.session_state.uploaded_docs = []


@st.cache_resource
def _service() -> AnswerService:
    return AnswerService()


@st.cache_resource
def _store() -> QdrantStore:
    return QdrantStore()


async def _scope_candidates(tenant_id: str) -> list[DocumentRecord]:
    """What a question may be scoped to: this tenant's documents.

    Same query as `_list_documents`, with a wider limit -- resolving a name a user typed needs a
    bigger net than rendering a list. It was a genuinely different query while a shared corpus
    existed; it is not any more, and the two are kept apart only by that limit.
    """
    await init_db()
    async with get_session() as session:
        return await list_document_records(session, tenant_id=tenant_id, limit=200)


async def _stage(record: DocumentRecord) -> None:
    """Write the `pending` row the flip will later update. Mirrors the API route's staging."""
    await init_db()
    async with get_session() as session:
        await stage_document_record(session, record)


async def _list_documents(tenant_id: str) -> list[DocumentRecord]:
    """Read the tenant's documents from the registry.

    Not cached: the point of the panel is to show current status, and a cached list would show
    `pending` after the ingest finished.
    """
    await init_db()
    async with get_session() as session:
        return await list_document_records(session, tenant_id=tenant_id)


with st.sidebar:
    st.subheader("API key")
    st.caption("Create one with `python scripts/create_tenant.py`.")
    api_key = st.text_input("Key", type="password", label_visibility="collapsed")
    # Re-resolve whenever the entered key changes, not only when no tenant is set yet --
    # otherwise pasting a second tenant's key silently keeps the first tenant's scope, which
    # looks like the app ignoring you and reads like a leak even though it isn't one.
    if api_key and api_key != st.session_state.get("resolved_for_key"):
        resolved = asyncio.run(resolve_tenant(api_key))
        st.session_state.resolved_for_key = api_key
        st.session_state.tenant_id = resolved
        if resolved is None:
            st.error("Invalid or revoked key.")
    if not api_key:
        st.session_state.tenant_id = None
        st.session_state.resolved_for_key = None
    if st.session_state.tenant_id:
        st.success(f"Tenant `{st.session_state.tenant_id[:8]}…`")

if st.session_state.tenant_id is None:
    st.info("Enter an API key in the sidebar to upload documents or ask questions.")
    st.stop()

tenant_id: str = st.session_state.tenant_id

with st.expander("Upload your own documents (visible to your tenant only)", expanded=False):
    st.caption(f"Supported: {', '.join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))}")
    uploaded_file = st.file_uploader("Choose a file", label_visibility="collapsed")
    if uploaded_file is not None:
        if not is_supported_upload(uploaded_file.name):
            st.error(f"Unsupported file type: {uploaded_file.name}")
        else:
            settings = get_settings()
            file_bytes = uploaded_file.getvalue()
            doc_id = upload_doc_id(tenant_id, file_bytes)
            digest = content_digest(file_bytes)
            # `document_upload_path` and `write_upload`, not a hand-joined path: this UI writes to
            # disk itself, so it needs the identical containment checks *and* the same
            # `<tenant>/<doc_id>/<filename>` layout. It previously built `<tenant>/<filename>` --
            # its own copy of the bug the API route had, which is what having two copies produces.
            file_path = document_upload_path(settings.upload_dir, tenant_id, doc_id, uploaded_file.name)
            write_upload(file_path, file_bytes)

            # Stage the row before ingesting, exactly as `POST /v1/documents` does. `ingest_document`
            # publishes by *flipping* an existing row's active version -- an UPDATE that raises
            # rather than inventing a row -- so without this every Streamlit upload would fail at
            # the commit point. It bypasses the queue, not the registry.
            asyncio.run(
                _stage(
                    DocumentRecord(
                        doc_id=doc_id,
                        tenant_id=tenant_id,
                        filename=file_path.name,
                        content_hash=digest,
                        file_extension=file_path.suffix,
                        file_size_bytes=len(file_bytes),
                        status=STATUS_PENDING,
                    )
                )
            )
            if doc_id not in st.session_state.uploaded_docs:
                with st.spinner(f"Ingesting {uploaded_file.name}..."):
                    # Deliberately still synchronous, unlike POST /v1/documents, which now
                    # returns 202 and lets a worker do this. Streamlit blocks its own script
                    # run either way, so a queue would buy nothing here beyond a status-polling
                    # loop to write -- and this UI retires when the React app lands
                    # (docs/EPIC_4_PLAN.md Phase 6). The row is published by ingest_document's
                    # version flip either way, so the two paths agree on what a finished row is.
                    #
                    # Streamlit's script model has no event loop of its own, same reason
                    # the /ask call below needs asyncio.run() rather than a plain await.
                    try:
                        chunk_count = asyncio.run(
                            ingest_document(
                                doc_id=doc_id,
                                file_path=file_path,
                                store=_store(),
                                tenant_id=tenant_id,
                                expected_digest=digest,
                            )
                        )
                    except EmptyDocumentError as exc:
                        # Surfaced rather than swallowed: a scanned PDF with no text layer parses
                        # "successfully" and yields nothing searchable, and silently recording it
                        # as ingested means the user only finds out by asking a question and
                        # getting an answer grounded in some other document.
                        st.error(str(exc))
                    else:
                        # `else`, not code after the `try`: the except branch calls `st.error`,
                        # which does not raise, so a trailing block would reach `chunk_count`
                        # genuinely unbound -- not merely unprovable. This comment used to blame
                        # `st.stop()` not being typed NoReturn; there is no `st.stop()` in that
                        # branch, and a reader checking for one concludes the `else` is redundant.
                        st.session_state.uploaded_docs.append(doc_id)
                        st.success(f"Ingested {uploaded_file.name} — {chunk_count} chunks (doc_id: {doc_id})")
            else:
                # Wording matters here. Streamlit reruns the whole script on every interaction and
                # `st.file_uploader` keeps returning the same file, so this branch is reached on
                # every rerun after a successful upload -- not because the user uploaded a
                # duplicate. "Already ingested" read as a refusal to ingest a genuinely new file.
                st.caption(f"{uploaded_file.name} is already ingested in this session.")

# The registry, not session state: session state is empty after a browser refresh, while these
# rows are what the tenant actually owns. Also the answer to "what documents do I have?", which
# /ask cannot give -- retrieval matches chunks semantically, so a meta-question about the
# collection gets answered from whatever text is nearest in embedding space.
with st.expander("My documents", expanded=not st.session_state.uploaded_docs):
    records = asyncio.run(_list_documents(tenant_id))
    if not records:
        st.caption("No documents uploaded yet.")
    else:
        st.dataframe(
            [
                {
                    "filename": record.filename,
                    "status": record.status,
                    "chunks": record.chunk_count,
                    "uploaded": record.uploaded_at,
                    "error": record.error_message or "",
                }
                for record in records
            ],
            hide_index=True,
        )

question = st.text_input(
    "Question",
    placeholder="What cathode materials show the highest cycling stability?",
    help="Name a document from the table above to restrict the search to it — the filename "
    "with its extension, or its doc_id.",
)

if st.button("Ask", type="primary") and question:
    # Same query as the table above, with a wider limit -- so this is a second registry read, not
    # a reuse of the expander's rows. (It used to claim "no extra query here", which was false the
    # moment the call became `_scope_candidates(tenant_id)`.) These were genuinely different
    # questions while a shared corpus existed -- "what may I scope to" included documents nobody
    # had uploaded -- and the two implementations disagreed, which 404'd every curated paper.
    # With the corpus gone there is one query and one scoping implementation.
    scope = (
        resolve_scope(question, asyncio.run(_scope_candidates(tenant_id)))
        if mentions_a_document(question)
        else DocumentScope()
    )

    if scope.names_nothing_owned:
        # Same contract as the API's 404: refuse rather than fall back to searching
        # everything, which would answer confidently about a different document.
        st.error(f"No document named {', '.join(scope.unknown)} in your documents.")
        st.stop()
    if scope.names_only_unready:
        # The API's 409. The document exists but has no chunks, so scoping to it returns a
        # confident "not mentioned" about a document nothing searched.
        st.warning(f"{', '.join(scope.not_ready)} is still ingesting or failed -- not searchable yet.")
        st.stop()

    with st.spinner("Retrieving, reranking, and generating..."):
        result = asyncio.run(_service().answer(question, tenant_id=tenant_id, doc_ids=scope.doc_ids or None))

    st.subheader("Answer")
    if scope.filenames:
        st.caption(f"Scoped to {', '.join(scope.filenames)} — your other documents were not searched.")
    st.write(result.text)
    if result.truncated:
        # Above the citations, not below, because the citation list is the *other* thing this
        # cuts short: blocks are emitted as the text is generated, so a truncated answer's
        # sources are incomplete too. Without this the reader sees a confident answer that
        # happens to stop mid-sentence and has no way to tell why.
        st.warning(
            "This answer hit the model's token limit and stopped early — the text is cut off and "
            "some sources are missing. Ask a narrower question rather than re-asking this one."
        )

    if result.citations:
        st.subheader("Citations")
        for citation in result.citations:
            page = f", page {citation.page_no}" if citation.page_no is not None else ""
            st.markdown(f"> {citation.quoted_text}\n\n— `{citation.doc_id}{page}` (`{citation.chunk_id}`)")
    else:
        st.info("No citations were returned for this answer.")

    st.subheader("Retrieved chunks")
    for doc in result.retrieved_chunks:
        meta = doc.metadata
        section_or_page = meta.get("section_path") or f"page {meta.get('page_no')}"
        # Filename first, doc_id only as the fallback for chunks written before it was stamped:
        # a 64-character content hash tells the reader nothing about which document this is.
        label = meta.get("filename") or meta.get("doc_id", "")
        with st.expander(f"[{meta.get('chunk_type', 'text')}] {label} — {section_or_page}"):
            if meta.get("chunk_type") == "figure" and meta.get("image_path"):
                st.image(meta["image_path"])
            st.markdown(doc.page_content)
