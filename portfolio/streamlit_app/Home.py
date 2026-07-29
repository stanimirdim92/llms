"""Demo UI for the /ask RAG pipeline: upload your own documents, ask a question, get a
cited answer grounded in the curated corpus plus your tenant's own uploads.

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
from app.generation.answer_service import AnswerService
from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS, is_supported_upload
from app.ingestion.pipeline import ingest_document
from app.ingestion.uploads import safe_filename, tenant_upload_dir, upload_doc_id
from app.logs import configure_logging
from app.vectorstore.qdrant_store import QdrantStore

configure_logging()

st.set_page_config(page_title="AI Engineer Portfolio — RAG Demo", page_icon="📄")
st.title("Scientific Document RAG")
st.caption("Ask a question about the curated materials-science / battery corpus, or upload your own documents first.")

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
            # Same hardened helpers the API route uses, rather than joining the path by
            # hand: this UI writes to disk itself, so it needs the identical containment
            # and filename checks, not a second unvalidated version of them.
            tenant_dir = tenant_upload_dir(settings.upload_dir, tenant_id)
            tenant_dir.mkdir(parents=True, exist_ok=True)
            file_bytes = uploaded_file.getvalue()
            file_path = tenant_dir / safe_filename(uploaded_file.name)
            file_path.write_bytes(file_bytes)

            doc_id = upload_doc_id(tenant_id, file_bytes)
            if doc_id not in st.session_state.uploaded_docs:
                with st.spinner(f"Ingesting {uploaded_file.name}..."):
                    # Deliberately still synchronous, unlike POST /v1/documents, which now
                    # returns 202 and lets a worker do this. Streamlit blocks its own script
                    # run either way, so a queue would buy nothing here beyond a status-polling
                    # loop to write -- and this UI retires when the React app lands
                    # (EPIC_4_PLAN.md Phase 6). It writes the row itself via ingest_document's
                    # terminal upsert, so the two paths agree on what a finished row looks like.
                    #
                    # Streamlit's script model has no event loop of its own, same reason
                    # the /ask call below needs asyncio.run() rather than a plain await.
                    chunk_count = asyncio.run(
                        ingest_document(doc_id=doc_id, file_path=file_path, store=_store(), tenant_id=tenant_id)
                    )
                st.session_state.uploaded_docs.append(doc_id)
                st.success(f"Ingested {uploaded_file.name} — {chunk_count} chunks (doc_id: {doc_id})")
            else:
                st.info(f"{uploaded_file.name} was already ingested.")

    if st.session_state.uploaded_docs:
        st.caption(f"This tenant's uploads: {', '.join(st.session_state.uploaded_docs)}")

question = st.text_input("Question", placeholder="What cathode materials show the highest cycling stability?")

if st.button("Ask", type="primary") and question:
    with st.spinner("Retrieving, reranking, and generating..."):
        # Streamlit's script model runs synchronously (no event loop of its own), so an
        # async call needs its own loop here rather than a plain await.
        result = asyncio.run(_service().answer(question, tenant_id=tenant_id))

    st.subheader("Answer")
    st.write(result.text)

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
        with st.expander(f"[{meta.get('chunk_type', 'text')}] {meta.get('doc_id', '')} — {section_or_page}"):
            if meta.get("chunk_type") == "figure" and meta.get("image_path"):
                st.image(meta["image_path"])
            st.markdown(doc.page_content)
