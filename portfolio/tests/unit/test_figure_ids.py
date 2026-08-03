"""Pins the figure_id numbering scheme.

`figure_id` feeds `chunk_id`, which feeds the Qdrant point id (`uuid5` of it). The store
has no delete path, so if this numbering ever shifts for an unchanged document, a
re-ingest writes *new* points and silently leaves the old ones behind -- still matching
the session filter, still retrievable, now stale. These tests exist so that regression
fails here instead of in production retrieval.

The caption cache is here for the same reason: it is keyed on `figure_id`, so the numbering
above is exactly what decides whether a re-ingest reuses a caption or pays for a new one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from docling_core.types.doc.document import DoclingDocument, PictureItem
from PIL import Image

from app.ingestion import figure_extractor

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
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


# ---------------------------------------------------------------------------------------------
# The caption cache, which is keyed on the figure_id above -- hence its living in this module.
# ---------------------------------------------------------------------------------------------


def _counting_captioner(calls: list[int]) -> Callable[[list[bytes]], list[str]]:
    def _caption(images: list[bytes]) -> list[str]:
        calls.append(len(images))
        return [_plausible_caption(index) for index in range(len(images))]

    return _caption


def test_a_second_pass_over_the_same_document_makes_no_vision_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-ingest is not rare -- a re-upload of the same file is the *same* document (`doc_id` is
    a content hash), every retry of a failed job re-enters here, and every corpus rebuild does
    too. Docling work was already cached; the vision calls were not, so a 30-figure paper paid
    30 of them each time to arrive at the same captions.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _counting_captioner(calls))
    items = [_Renderable(self_ref=f"#/pictures/{index}") for index in range(3)]

    first = figure_extractor.extract_figures(_document_yielding(items), tmp_path)
    second = figure_extractor.extract_figures(_document_yielding(items), tmp_path)

    assert calls == [3], "the second pass must not reach the vision model at all"
    assert [figure.caption for figure in second] == [figure.caption for figure in first]


def test_refusals_are_cached_too_so_they_are_not_re_billed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The **raw** model output is cached, before the usability filter. Caching only the
    captions that survived would re-bill exactly the figures the model had already declined to
    describe -- the icons and rules, which are also the most numerous. Those are dropped after
    the cache read, so the document still yields no figures either time.
    """
    calls: list[int] = []

    def _refuse(images: list[bytes]) -> list[str]:
        calls.append(len(images))
        return ["NO_USEFUL_CONTENT"] * len(images)

    monkeypatch.setattr(figure_extractor, "_caption_all", _refuse)
    items = [_Renderable(self_ref="#/pictures/0")]

    assert figure_extractor.extract_figures(_document_yielding(items), tmp_path) == []
    assert figure_extractor.extract_figures(_document_yielding(items), tmp_path) == []
    assert calls == [1]


def test_only_the_uncached_figures_are_sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A document that grows a figure must pay for that figure only. Asserting on the batch
    *size* rather than the output, because the cost is what is being tested.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _counting_captioner(calls))

    figure_extractor.extract_figures(_document_yielding([_Renderable(self_ref="#/pictures/0")]), tmp_path)
    figure_extractor.extract_figures(
        _document_yielding([_Renderable(self_ref="#/pictures/0"), _Renderable(self_ref="#/pictures/1")]), tmp_path
    )

    assert calls == [1, 1]


def test_a_shifted_index_misses_the_cache_rather_than_reusing_a_stranger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety property of keying on `figure_id`. Anything that changes which regions Docling
    finds -- an upgrade, a different render -- shifts the index, so the cache misses and the
    figure is described afresh. Keying on position-in-batch instead would hand figure 1 the
    caption written for what used to be figure 1 and is now something else entirely.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _counting_captioner(calls))

    # First pass: one picture, at index 0.
    figure_extractor.extract_figures(_document_yielding([_Renderable(self_ref="#/pictures/0")]), tmp_path)
    # Second pass: a picture appears *before* it, so the original is now index 1.
    figures = figure_extractor.extract_figures(
        _document_yielding([_Renderable(self_ref="#/pictures/9"), _Renderable(self_ref="#/pictures/0")]), tmp_path
    )

    assert calls == [1, 1], "index 01 is new to the cache; index 00 is not"
    assert [figure.figure_id for figure in figures] == ["fig-000-00", "fig-000-01"]


def test_the_cache_entry_sits_beside_the_image_it_describes(tmp_path: Path) -> None:
    """Same directory, same stem. It is `data/processed/<doc_id>/figures/`, which is already
    wiped by deleting that document's processed directory -- so there is no second cache to
    remember to clear.
    """
    figure_extractor.extract_figures(_document_yielding([_Renderable(self_ref="#/pictures/0")]), tmp_path)

    assert (tmp_path / "fig-000-00.png").exists()
    assert (tmp_path / "fig-000-00.txt").read_text(encoding="utf-8") == _plausible_caption(0)
