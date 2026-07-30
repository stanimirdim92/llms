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


# Above `figure_min_dimension_px` (64), so these are captioned rather than skipped as icons.
# The numbering tests below are about index accounting, not size, so they must not trip the
# small-image filter.
_BIG = 128
_ICON = 16


class _Renderable(PictureItem):
    """A picture Docling could rasterize, large enough to be worth captioning."""

    def get_image(self, *_args: object, **_kwargs: object) -> Image.Image:
        return Image.new("RGB", (_BIG, _BIG), "white")


class _IconSized(PictureItem):
    """A renderable image too small to describe -- a contact icon, a logo, a rule."""

    def get_image(self, *_args: object, **_kwargs: object) -> Image.Image:
        return Image.new("RGB", (_ICON, _ICON), "white")


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


def _plausible_caption(index: int) -> str:
    """Long enough to clear `figure_min_caption_chars`, and identifiable so alignment can be
    asserted. The stub used to return "caption 0", which the unusable-caption filter now
    correctly rejects as too short to describe anything -- a fixture that quietly exercised the
    drop path instead of the happy path.
    """
    return f"Figure {index}: a line plot showing measured capacity against cycle number."


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Captioning is the only thing in this module that talks to Anthropic."""
    monkeypatch.setattr(
        figure_extractor, "_caption_all", lambda images: [_plausible_caption(i) for i in range(len(images))]
    )


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

    assert [f.caption for f in figures] == [_plausible_caption(i) for i in range(3)]
    assert [f.figure_id for f in figures] == ["fig-000-00", "fig-000-01", "fig-000-02"]


def test_no_pictures_makes_no_captioning_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A document with no figures must not reach the batching call at all."""

    def _fail(_images: list[bytes]) -> list[str]:
        raise AssertionError("_caption_all called for a document with no figures")

    monkeypatch.setattr(figure_extractor, "_caption_all", _fail)

    assert figure_extractor.extract_figures(_document_yielding([]), tmp_path) == []


def test_icon_sized_images_are_never_captioned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Docling reports contact icons and logos as PictureItems, indistinguishable from charts.

    Observed in production: a one-page CV produced five "figures", all icons, each costing a
    vision call and each becoming a retrievable chunk. Asserting on the images actually *sent*
    rather than on the output, because the cost is incurred whether or not the caption is kept.
    """
    sent: list[int] = []

    def _record(images: list[bytes]) -> list[str]:
        sent.append(len(images))
        return ["a perfectly usable caption describing a chart in detail"] * len(images)

    monkeypatch.setattr(figure_extractor, "_caption_all", _record)
    items = [_IconSized(self_ref="#/pictures/0"), _Renderable(self_ref="#/pictures/1")]

    figures = figure_extractor.extract_figures(_document_yielding(items), tmp_path)

    assert sent == [1], "the icon should never have reached the vision call"
    assert [f.figure_id for f in figures] == ["fig-000-01"]


def test_a_skipped_icon_still_consumes_its_index(tmp_path: Path) -> None:
    """Same invariant as the unrenderable case, for the new filter: figure_id feeds chunk_id feeds
    the Qdrant point id, so closing the gap would orphan every already-stored figure chunk.
    """
    items = [
        _Renderable(self_ref="#/pictures/0"),
        _IconSized(self_ref="#/pictures/1"),
        _Renderable(self_ref="#/pictures/2"),
    ]

    figures = figure_extractor.extract_figures(_document_yielding(items), tmp_path)

    assert [f.figure_id for f in figures] == ["fig-000-00", "fig-000-02"]


def test_a_document_of_only_icons_makes_no_captioning_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(_images: list[bytes]) -> list[str]:
        raise AssertionError("_caption_all called for a document with only icons")

    monkeypatch.setattr(figure_extractor, "_caption_all", _fail)
    items = [_IconSized(self_ref=f"#/pictures/{i}") for i in range(4)]

    assert figure_extractor.extract_figures(_document_yielding(items), tmp_path) == []


@pytest.mark.parametrize(
    "caption",
    [
        "I'm not able to see the image you're referring to -- it seems the figure wasn't included.",
        "I cannot see any image in your message. Could you please try uploading the image again?",
        "NO_USEFUL_CONTENT",
        "Unable to see the attached figure, please re-upload it so I can describe the contents.",
        "A chart.",  # too short to be a description
        "",
    ],
)
def test_unusable_captions_do_not_become_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caption: str) -> None:
    """A caption is the figure's *only* searchable text, so an unusable one is worse than no
    figure at all: it becomes a chunk that competes with real content.

    This is the bug a real upload surfaced -- four of five reranked chunks were the model saying
    it could not see an image, which is what the answer was then grounded in.
    """
    monkeypatch.setattr(figure_extractor, "_caption_all", lambda images: [caption] * len(images))

    figures = figure_extractor.extract_figures(_document_yielding([_Renderable(self_ref="#/pictures/0")]), tmp_path)

    assert figures == []


def test_a_real_caption_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The filters must not be so eager that they drop legitimate descriptions."""
    good = (
        "A line plot of discharge capacity against cycle number for three cathode materials, "
        "showing NMC811 retaining the highest capacity after 500 cycles."
    )
    monkeypatch.setattr(figure_extractor, "_caption_all", lambda images: [good] * len(images))

    figures = figure_extractor.extract_figures(_document_yielding([_Renderable(self_ref="#/pictures/0")]), tmp_path)

    assert [f.caption for f in figures] == [good]
