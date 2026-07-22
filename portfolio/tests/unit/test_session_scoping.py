from qdrant_client.models import FieldCondition, Filter, MatchAny

from app.ingestion.uploads import upload_doc_id
from app.vectorstore.qdrant_store import _build_filter


def test_filter_with_no_session_only_searches_global() -> None:
    where = _build_filter(chunk_types=None, session_id=None)

    assert where == Filter(must=[FieldCondition(key="metadata.session_id", match=MatchAny(any=["global"]))])


def test_filter_with_session_includes_global_and_session() -> None:
    where = _build_filter(chunk_types=None, session_id="abc123")

    assert where == Filter(must=[FieldCondition(key="metadata.session_id", match=MatchAny(any=["global", "abc123"]))])


def test_filter_with_session_equal_to_global_does_not_duplicate() -> None:
    where = _build_filter(chunk_types=None, session_id="global")

    assert where == Filter(must=[FieldCondition(key="metadata.session_id", match=MatchAny(any=["global"]))])


def test_filter_combines_chunk_types_and_session_with_and() -> None:
    where = _build_filter(chunk_types=["table", "figure"], session_id="abc123")

    assert where == Filter(
        must=[
            FieldCondition(key="metadata.session_id", match=MatchAny(any=["global", "abc123"])),
            FieldCondition(key="metadata.chunk_type", match=MatchAny(any=["table", "figure"])),
        ]
    )


def test_upload_doc_id_is_deterministic_per_session_and_content() -> None:
    doc_id_a = upload_doc_id("session-1", b"same bytes")
    doc_id_b = upload_doc_id("session-1", b"same bytes")

    assert doc_id_a == doc_id_b
    assert doc_id_a.startswith("session-1-")


def test_upload_doc_id_differs_across_sessions_for_same_content() -> None:
    doc_id_a = upload_doc_id("session-1", b"same bytes")
    doc_id_b = upload_doc_id("session-2", b"same bytes")

    assert doc_id_a != doc_id_b


def test_upload_doc_id_differs_across_content_for_same_session() -> None:
    doc_id_a = upload_doc_id("session-1", b"content a")
    doc_id_b = upload_doc_id("session-1", b"content b")

    assert doc_id_a != doc_id_b
