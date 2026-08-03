"""Pins the figure_id numbering scheme.

`figure_id` feeds `chunk_id`, which feeds the Qdrant point id (`uuid5` of it). The store
has no delete path, so if this numbering ever shifts for an unchanged document, a
re-ingest writes *new* points and silently leaves the old ones behind -- still matching
the session filter, still retrievable, now stale. These tests exist so that regression
fails here instead of in production retrieval.

The caption cache is here because it was *wrongly* keyed on `figure_id` -- see
`test_a_figure_never_receives_a_caption_written_for_a_different_figure`, which is the test the
first version of that cache did not have. Numbering and caching are one subject as a result.
"""

from __future__ import annotations

import hashlib
import io
import os
import pathlib
from typing import TYPE_CHECKING, ClassVar

import pytest
from docling_core.types.doc.document import DoclingDocument, PictureItem
from PIL import Image
from pydantic import SecretStr

from app.ingestion import figure_extractor

_REAL_CAPTION_ALL = figure_extractor._caption_all
"""Captured at import, before the autouse `_no_network` fixture replaces the module attribute --
the one test that exercises `_caption_all` itself needs the real implementation."""

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


def test_captions_stay_aligned_with_their_figures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rendering and captioning are separate passes, so a zip misalignment would attach the wrong
    caption to a figure -- wrong, and invisible without this assertion.

    Three *distinct* pictures, because the cache now deduplicates a batch by image digest: with
    the module's byte-identical `_Renderable` these would legitimately collapse to one caption and
    the alignment this test exists for would be trivially satisfied.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner(calls))
    items = [_picture_of(shade) for shade in (10, 20, 30)]

    figures = figure_extractor.extract_figures(_document_yielding(items), tmp_path)

    assert [f.figure_id for f in figures] == ["fig-000-00", "fig-000-01", "fig-000-02"]
    assert [f.caption for f in figures] == [_expected_caption(shade) for shade in (10, 20, 30)]


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
# The caption cache
# ---------------------------------------------------------------------------------------------
#
# Every picture below renders a *distinct* colour, which the fixtures above do not: `_Renderable`
# is always white, so any two of them are byte-identical. That was harmless while the cache was
# keyed on `figure_id`; it is the whole point now that the key is a digest of the image, because
# byte-identical pictures legitimately share one entry. A test that wants to observe two
# independent cache entries therefore has to use two different images.


def _picture_of(shade: int) -> PictureItem:
    """A renderable picture whose pixels are unique to `shade`.

    A subclass per call, because `PictureItem` is a pydantic model: a plain instance attribute
    raises "object has no field", and a class attribute becomes a `ModelPrivateAttr` descriptor
    rather than the value. Closing over `shade` sidesteps both.
    """

    class _Shaded(PictureItem):
        def get_image(self, *_args: object, **_kwargs: object) -> Image.Image:
            return Image.new("RGB", (_BIG, _BIG), (shade, shade, shade))

    return _Shaded(self_ref=f"#/pictures/{shade % 10}")


def _identifying_captioner(calls: list[int]) -> Callable[[list[bytes]], list[str]]:
    """Captions that name the image they describe, so a wrong one is *visible*.

    This is the part the first version of these tests got wrong. Its stub returned
    `_plausible_caption(position_in_batch)`, so two figures captioned in the same pass received
    identical strings and no assertion on caption content could distinguish "this figure's
    caption" from "some other figure's caption". The digest is of the bytes actually sent, which
    is the same thing the cache keys on -- so a collision shows up as a caption naming the wrong
    digest rather than as a passing test.
    """

    def _caption(images: list[bytes]) -> list[str]:
        calls.append(len(images))
        return [f"Figure {hashlib.sha256(image).hexdigest()[:8]}: a line plot of capacity." for image in images]

    return _caption


def _expected_caption(shade: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (_BIG, _BIG), (shade, shade, shade)).save(buffer, "PNG")
    return f"Figure {hashlib.sha256(buffer.getvalue()).hexdigest()[:8]}: a line plot of capacity."


def test_a_second_pass_over_the_same_document_makes_no_vision_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-ingest is not rare -- a re-upload of the same file is the *same* document (`doc_id` is
    a hash of the tenant *and* the bytes, so identical content re-uploaded by the same tenant is
    the same document), every retry of a failed job re-enters here, and every corpus rebuild does
    too. Docling work was already cached; the vision calls were not, so a 30-figure paper paid
    30 of them each time to arrive at the same captions.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner(calls))
    items = [_picture_of(shade) for shade in (10, 20, 30)]

    first = figure_extractor.extract_figures(_document_yielding(items), tmp_path)
    second = figure_extractor.extract_figures(_document_yielding(items), tmp_path)

    assert calls == [3], "the second pass must not reach the vision model at all"
    assert [figure.caption for figure in second] == [figure.caption for figure in first]


def test_a_figure_never_receives_a_caption_written_for_a_different_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety property, and the one the first version of this cache got wrong.

    Keyed on `figure_id` -- `fig-{page}-{index}` over *all* picture items -- inserting a picture
    earlier in a document shifted every later index down onto an id an earlier figure already
    held. Nothing deletes stale entries, so that was a cache **collision**: measured, the newly
    inserted figure was handed the caption written for the figure that used to be at index 0, and
    a caption is a figure's only searchable text.

    The predecessor of this test set up exactly this scenario and asserted only the call counts
    and the id list -- both of which a collision satisfies. Assert content, or this proves
    nothing.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner(calls))

    figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)
    # Shade 20 is inserted *before* shade 10, so it now occupies `fig-000-00` -- the id whose
    # cache entry shade 10 wrote on the first pass.
    figures = figure_extractor.extract_figures(_document_yielding([_picture_of(20), _picture_of(10)]), tmp_path)

    assert [figure.figure_id for figure in figures] == ["fig-000-00", "fig-000-01"]
    assert figures[0].caption == _expected_caption(20), "fig-000-00 was handed a stranger's caption"
    assert figures[1].caption == _expected_caption(10), "the moved figure lost its own caption"
    assert calls == [1, 1], "only the genuinely new image should have been sent"


def test_a_figure_that_merely_moved_still_hits_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other side of content addressing, and a real improvement over the id-keyed version:
    an unchanged picture that shifted position is the same picture, so it must not be re-billed.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner(calls))

    figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)
    figures = figure_extractor.extract_figures(_document_yielding([_picture_of(20), _picture_of(10)]), tmp_path)

    assert calls == [1, 1], "shade 10 moved from index 0 to index 1 and must still hit"
    # Content, not just the call count. Without this the test passes under the old `figure_id` key
    # too, where the moved figure "hits" by being handed a stranger's caption.
    assert figures[1].caption == _expected_caption(10), "it must hit with its *own* caption"


def test_identical_pictures_cost_one_vision_call_on_the_very_first_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same logo on every page is one call, not one per page -- **including** the first time
    the document is seen, which is where the saving actually is.

    The first version of this test called `extract_figures` once to warm the cache before the
    three-picture document, so it only proved the cross-*run* behaviour and passed while the first
    ingest still paid three calls: the code collected every cache miss and sent them all, and three
    identical images are three misses. One pass, no pre-warm.

    The cost was the smaller half. Three independent calls on a non-deterministic model produce
    three *different* captions for one picture, so three chunks described the same image
    differently -- and a later re-ingest collapsed them onto whichever the cache happened to hold.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner(calls))

    figures = figure_extractor.extract_figures(
        _document_yielding([_picture_of(10), _picture_of(10), _picture_of(10)]), tmp_path
    )

    assert calls == [1], "one distinct image, so one call -- on the first pass, not the second"
    assert [figure.figure_id for figure in figures] == ["fig-000-00", "fig-000-01", "fig-000-02"]
    assert {figure.caption for figure in figures} == {_expected_caption(10)}, "all three, same caption"
    assert len(list(tmp_path.glob("caption-*.txt"))) == 1


def test_a_mix_of_new_and_duplicate_images_pays_once_per_distinct_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The general form: five pictures, two distinct, one batch of two."""
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner(calls))
    shades = (10, 20, 10, 20, 10)

    figures = figure_extractor.extract_figures(_document_yielding([_picture_of(s) for s in shades]), tmp_path)

    assert calls == [2]
    assert [figure.caption for figure in figures] == [_expected_caption(s) for s in shades]


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
    items = [_picture_of(10)]

    assert figure_extractor.extract_figures(_document_yielding(items), tmp_path) == []
    assert figure_extractor.extract_figures(_document_yielding(items), tmp_path) == []
    assert calls == [1]


def test_only_the_uncached_figures_are_sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A document that grows a figure must pay for that figure only. Asserting on the batch
    *size* rather than the output, because the cost is what is being tested.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner(calls))

    figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)
    figure_extractor.extract_figures(_document_yielding([_picture_of(10), _picture_of(20)]), tmp_path)

    assert calls == [1, 1]


def test_an_empty_cache_entry_is_treated_as_a_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`write_text` is not atomic, so an interrupted write or a full disk leaves a zero-byte
    entry. Read back as `""` it is dropped as unusable and logged identically to a model refusal,
    and it never self-heals -- one bad write would suppress that figure from search forever.
    The write path is now temp-file-plus-replace, and the read path treats empty as absent, so
    neither half depends on the other holding.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner(calls))
    figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)
    entry = next(path for path in tmp_path.glob("caption-*.txt"))
    entry.write_text("", encoding="utf-8")

    figures = figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)

    assert calls == [1, 1], "the truncated entry must be re-captioned, not read back as empty"
    assert [figure.caption for figure in figures] == [_expected_caption(10)]


def test_an_undecodable_cache_entry_does_not_fail_the_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It used to raise `UnicodeDecodeError` out of `extract_figures`, so one corrupt byte in one
    cached caption failed the whole document's ingest -- and via the worker marked it `failed`.
    """
    calls: list[int] = []
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner(calls))
    figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)
    entry = next(path for path in tmp_path.glob("caption-*.txt"))
    entry.write_bytes(b"\xff\xfe not utf-8")

    figures = figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)

    assert [figure.caption for figure in figures] == [_expected_caption(10)]


def test_a_cache_write_failure_does_not_fail_the_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """This is a cache. A read-only or full disk should make the next ingest slower, not turn a
    successfully captioned document into a failed one.
    """
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner([]))

    def _refuse_to_write(_self: pathlib.Path, _data: str, **_kwargs: object) -> int:
        raise OSError("no space left on device")

    # Patched on `pathlib.Path` itself, not on `figure_extractor.Path`: that module imports
    # `Path` under TYPE_CHECKING only, so the attribute does not exist at runtime.
    monkeypatch.setattr(pathlib.Path, "write_text", _refuse_to_write)

    figures = figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)

    assert [figure.caption for figure in figures] == [_expected_caption(10)]


def test_the_cache_entry_sits_in_the_figure_directory(tmp_path: Path) -> None:
    """`data/processed/<doc_id>/figures/`, alongside the PNGs. Note that deleting the *parse*
    cache -- `processed/<doc_id>.json`, a sibling file, not inside this directory -- does not
    clear these; with a content-addressed key that is harmless, since a stale entry can only
    ever be reused for a byte-identical image.
    """
    figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)

    assert (tmp_path / "fig-000-00.png").exists()
    assert len(list(tmp_path.glob("caption-*.txt"))) == 1


def test_a_caption_cut_off_at_the_token_ceiling_is_not_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`/ask` got truncation detection and figure captioning did not, which was the same finding
    left half-fixed.

    A caption cut at `max_tokens` is well past `figure_min_caption_chars`, so the usability filter
    keeps it -- and a figure's caption is its only searchable text, so a mid-sentence fragment
    becomes the figure's entire retrievable content while reading like a real description. It would
    also be *cached* under the image digest and re-served on every later ingest.

    Driven through the real `_caption_all` with a stubbed model, because the check lives there
    rather than in `extract_figures`.
    """

    class _Truncated:
        content = "A line plot of discharge capacity against cycle number for three cathode mat"
        response_metadata: ClassVar[dict[str, str]] = {"stop_reason": "max_tokens"}

    class _Complete:
        content = "A line plot of discharge capacity against cycle number for three cathode materials."
        response_metadata: ClassVar[dict[str, str]] = {"stop_reason": "end_turn"}

    class _StubLLM:
        def batch(self, messages: list[object], config: dict | None = None) -> list[_Truncated | _Complete]:
            assert config is not None
            responses: list[_Truncated | _Complete] = [_Truncated(), _Complete()]
            return responses[: len(messages)]

    monkeypatch.setattr(figure_extractor, "ChatAnthropic", lambda **_kwargs: _StubLLM())
    monkeypatch.setattr(figure_extractor.get_settings(), "anthropic_api_key", SecretStr("sk-ant-x"))

    # `_REAL_CAPTION_ALL`, not `figure_extractor._caption_all`: the autouse `_no_network` fixture
    # has replaced the module attribute, and the check under test lives inside the real function.
    captions = _REAL_CAPTION_ALL([b"first image", b"second image"])

    assert captions[0] == "", "a truncated caption must be dropped, not stored"
    assert captions[1].startswith("A line plot")


def test_the_cache_filename_is_the_digest_of_the_png_that_was_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache filename must be the digest of the PNG that is actually on disk.

    That is the invariant the cache rests on, and it is what this pins. It deliberately does **not**
    claim to pin "encoded once": Pillow's encode is deterministic, so a second `image.save(path)`
    produces identical bytes and is indistinguishable from here -- measured, by mutating the code
    back to a double encode and watching this stay green. The single encode is a CPU saving, and the
    reason it is *also* correctness-relevant is exactly what this asserts: if the two encodes ever
    diverged (a Pillow upgrade changing the default compression level would do it) the cache would
    miss for every figure on every ingest while looking like it worked, and this test is what would
    catch that.
    """
    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner([]))

    figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)

    png = (tmp_path / "fig-000-00.png").read_bytes()
    entry = next(path for path in tmp_path.glob("caption-*.txt"))
    assert entry.name == f"caption-{hashlib.sha256(png).hexdigest()[:32]}.txt"


def test_two_writers_of_one_image_do_not_share_a_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The temp path must be unique per writer, not per digest.

    It was `path.with_suffix(".tmp")` -- a function of the digest alone -- so two workers ingesting
    the same `doc_id` (two uploads of identical bytes derive one id, and `WORKER_CONCURRENCY`
    defaults to 2) wrote the same temp file and one `replace`d a file the other was still writing.
    That is precisely what the temp file exists to prevent.
    """
    captured: list[str] = []
    real_replace = pathlib.Path.replace

    def _record_then_replace(self: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        captured.append(self.name)
        return real_replace(self, target)

    monkeypatch.setattr(figure_extractor, "_caption_all", _identifying_captioner([]))
    monkeypatch.setattr(pathlib.Path, "replace", _record_then_replace)

    figure_extractor.extract_figures(_document_yielding([_picture_of(10)]), tmp_path)

    assert captured, "the atomic write must go through a temp file"
    assert captured[0] != "caption-.tmp"
    assert captured[0].endswith(".tmp")
    assert str(os.getpid()) in captured[0], "the pid is what makes it unique between workers"
    assert not list(tmp_path.glob("*.tmp")), "and it must not be left behind"
