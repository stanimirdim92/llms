"""Demo UI for the /ask RAG pipeline: question box, cited answer, retrieved tables/figures."""

import streamlit as st

from app.generation.answer_service import AnswerService

st.set_page_config(page_title="AI Engineer Portfolio — RAG Demo", page_icon="📄")
st.title("Scientific Document RAG — Iris.ai Track")
st.caption("Ask a question about the ingested materials-science / battery corpus. Every answer is grounded in a specific chunk.")


@st.cache_resource
def _service() -> AnswerService:
    return AnswerService()


question = st.text_input("Question", placeholder="What cathode materials show the highest cycling stability?")

if st.button("Ask", type="primary") and question:
    with st.spinner("Retrieving, reranking, and generating..."):
        result = _service().answer(question)

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
    for chunk in result.retrieved_chunks:
        with st.expander(f"[{chunk.chunk_type}] {chunk.doc_id} — {chunk.section_path or 'page ' + str(chunk.page_no)}"):
            if chunk.chunk_type == "figure":
                image_path = chunk.metadata.get("image_path") if hasattr(chunk, "metadata") else None
                if image_path:
                    st.image(image_path)
            st.markdown(chunk.text)
