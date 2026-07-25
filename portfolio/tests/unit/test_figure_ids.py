"""Pins the figure_id numbering scheme.

`figure_id` feeds `chunk_id`, which feeds the Qdrant point id (`uuid5` of it). The store
has no delete path, so if this numbering ever shifts for an unchanged document, a
re-ingest writes *new* points and silently leaves the old ones behind -- still matching
the session filter, still retrievable, now stale. These tests exist so that regression
fails here instead of in production retrieval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from docling_core.types.doc.document import DoclingDocument, PictureItem
from PIL import Image

from app.ingestion import figure_extractor

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path


class _Renderable(PictureItem):
    """A picture Docling could rasterize."""

    def get_image(self, *_args: object, **_kwargs: object) -> Image.Image:
        return Image.new("RGB", (4, 4), "white")


class _Unrenderable(PictureItem):
    """A picture item with no image -- `extract_figures` skips these."""

    def get_image(self, *_args: object, **_kwargs: object) -> None:
        return None


def _document_yielding(items: Sequence[PictureItem]) -> DoclingDocument:
    """A DoclingDocument whose `iterate_items` yields exactly `items`.

    Subclassed rather than monkeypatched: `DoclingDocument` is a pydantic model, so
    assigning a method onto an instance raises "object has no field". `Sequence`, not
    `list`, because `list` is invariant -- a `list[_Renderable]` isn't a `list[PictureItem]`.
    """

    class _StubDocument(DoclingDocument):
        def iterate_items(self, *_args: object, **_kwargs: object) -> Iterator[tuple[PictureItem, int]]:
            return ((item, 0) for item in items)

    return _StubDocument(name="test")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Captioning is the only thing in this module that talks to Anthropic."""
    monkeypatch.setattr(figure_extractor, "_caption_all", lambda images: [f"caption {i}" for i in range(len(images))])


def test_unrenderable_picture_still_consumes_its_index(tmp_path: Path) -> None:
    """The middle picture yields no image, so it produces no figure -- but the one after
    it must still be numbered 02, not 01. Renumbering to close the gap would change every
    downstream point id.
    """
    items = [
        _Renderable(self_ref="#/pictures/0"),
        _Unrenderable(self_ref="#/pictures/1"),
        _Renderable(self_ref="#/pictures/2"),
    ]

    figures = figure_extractor.extract_figures(_document_yielding(items), tmp_path)

    assert [f.figure_id for f in figures] == ["fig-000-00", "fig-000-02"]


def test_captions_stay_aligned_with_their_figures(tmp_path: Path) -> None:
    """Rendering and captioning are two separate passes now, so a zip misalignment would
    attach the wrong caption to a figure -- wrong, and invisible without this assertion.
    """
    items = [_Renderable(self_ref=f"#/pictures/{i}") for i in range(3)]

    figures = figure_extractor.extract_figures(_document_yielding(items), tmp_path)

    assert [f.caption for f in figures] == ["caption 0", "caption 1", "caption 2"]
    assert [f.figure_id for f in figures] == ["fig-000-00", "fig-000-01", "fig-000-02"]


def test_no_pictures_makes_no_captioning_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A document with no figures must not reach the batching call at all."""

    def _fail(_images: list[bytes]) -> list[str]:
        raise AssertionError("_caption_all called for a document with no figures")

    monkeypatch.setattr(figure_extractor, "_caption_all", _fail)

    assert figure_extractor.extract_figures(_document_yielding([]), tmp_path) == []
