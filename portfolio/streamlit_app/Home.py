"""Demo UI for the /ask RAG pipeline: upload your own documents, ask a question, get a
cited answer grounded in the curated corpus plus anything you've uploaded this session.
"""

import asyncio
import uuid

import streamlit as st

from app.config import get_settings
from app.generation.answer_service import AnswerService
from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS, is_supported_upload
from app.ingestion.pipeline import ingest_document
from app.ingestion.uploads import upload_doc_id
from app.vectorstore.qdrant_store import QdrantStore

st.set_page_config(page_title="AI Engineer Portfolio — RAG Demo", page_icon="📄")
st.title("Scientific Document RAG — Track")
st.caption("Ask a question about the curated materials-science / battery corpus, or upload your own documents first.")

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex
if "uploaded_docs" not in st.session_state:
    st.session_state.uploaded_docs = []


@st.cache_resource
def _service() -> AnswerService:
    return AnswerService()


@st.cache_resource
def _store() -> QdrantStore:
    return QdrantStore()


with st.expander("Upload your own documents (this browser session only)", expanded=False):
    st.caption(f"Supported: {', '.join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))}")
    uploaded_file = st.file_uploader("Choose a file", label_visibility="collapsed")
    if uploaded_file is not None:
        if not is_supported_upload(uploaded_file.name):
            st.error(f"Unsupported file type: {uploaded_file.name}")
        else:
            settings = get_settings()
            session_dir = settings.upload_dir / st.session_state.session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            file_bytes = uploaded_file.getvalue()
            file_path = session_dir / uploaded_file.name
            file_path.write_bytes(file_bytes)

            doc_id = upload_doc_id(st.session_state.session_id, file_bytes)
            if doc_id not in st.session_state.uploaded_docs:
                with st.spinner(f"Ingesting {uploaded_file.name}..."):
                    chunk_count = ingest_document(
                        doc_id=doc_id, file_path=file_path, store=_store(), session_id=st.session_state.session_id
                    )
                st.session_state.uploaded_docs.append(doc_id)
                st.success(f"Ingested {uploaded_file.name} — {chunk_count} chunks (doc_id: {doc_id})")
            else:
                st.info(f"{uploaded_file.name} was already ingested this session.")

    if st.session_state.uploaded_docs:
        st.caption(f"This session's uploads: {', '.join(st.session_state.uploaded_docs)}")

question = st.text_input("Question", placeholder="What cathode materials show the highest cycling stability?")

if st.button("Ask", type="primary") and question:
    with st.spinner("Retrieving, reranking, and generating..."):
        # Streamlit's script model runs synchronously (no event loop of its own), so an
        # async call needs its own loop here rather than a plain await.
        result = asyncio.run(_service().answer(question, session_id=st.session_state.session_id))

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
