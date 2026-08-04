"""Save figure images from a parsed document and caption them with Claude vision so they
become searchable chunks.

Docling itself renders each PictureItem's image during parsing (when
`generate_picture_images=True`, set in `parser.py`) and exposes it via
`PictureItem.get_image(document)` -- so this does NOT re-open/re-crop the original PDF
with a second library. An earlier version of this file used PyMuPDF for that, which was
both an unnecessary dependency and required manually flipping Docling's bbox coordinate
origin to match PyMuPDF's, a needless source of bugs Docling already solves internally.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from docling_core.types.doc.document import DoclingDocument, PictureItem
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage

from app.config import get_settings

if TYPE_CHECKING:
    from pathlib import Path

    from PIL import Image

log = structlog.get_logger(__name__)

# Deliberately not "from a scientific paper" any more. Uploads are whatever a user has -- a CV, a
# report, a slide deck -- and priming the model for a scientific figure when it is looking at a
# contact icon invites exactly the confused non-answers this prompt used to produce.
_CAPTION_PROMPT = (
    "Describe this image from a document in 2-4 sentences. "
    "State what kind of image it is (plot, micrograph, schematic, diagram, photo, logo, icon, etc.), "
    "the axes or quantities shown if it is a chart, and the key information it conveys. "
    "Be factual and specific — this description is the only way the image will be found by search. "
    "If the image carries no information worth searching for (a decorative icon, a rule, a blank "
    "region), reply with exactly: NO_USEFUL_CONTENT"
)

# The sentinel above, plus the shapes a model reaches for when it cannot make sense of an image.
# Checked against captions because a caption is the figure's only searchable text: left in, a
# refusal becomes a chunk that outranks real content. Observed in production -- a CV's five icon
# "figures" produced four captions along the lines of "I'm not able to see the image you're
# referring to -- it seems the figure wasn't included with your message."
_UNUSABLE_CAPTION_MARKERS = (
    "no_useful_content",
    "not able to see",
    "unable to see",
    "cannot see",
    "can't see",
    "wasn't included",
    "was not included",
    "didn't come through",
    "did not come through",
    "no image",
    "try uploading",
    "re-upload",
    "reupload",
    "upload the image again",
)


@dataclass(frozen=True)
class ExtractedFigure:
    figure_id: str
    page_no: int
    image_path: Path
    caption: str


def _caption_message(image_bytes: bytes) -> HumanMessage:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    return HumanMessage(
        content=[
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
            },
            {"type": "text", "text": _CAPTION_PROMPT},
        ]
    )


def _response_text(response: BaseMessage) -> str:
    content = response.content
    if isinstance(content, str):
        return content.strip()
    text_blocks = (block for block in content if isinstance(block, dict) and block.get("type") == "text")
    return "".join(block.get("text", "") for block in text_blocks).strip()


_CAPTION_MAX_TOKENS = 300
"""Ceiling for one caption. A caption is short by construction -- 2-4 sentences."""

_TRUNCATED_STOP_REASON = "max_tokens"
"""Anthropic's `stop_reason` when the ceiling above cut generation off.

The same finding that produced `Answer.truncated` for `/ask` applies here and was missed the first
time: a caption cut at `max_tokens` is still well past `figure_min_caption_chars`, so
`_is_unusable_caption` keeps it, and a figure's caption is its *only* searchable text. It is also
cached now, so one truncated caption is re-served on every later ingest of that image. Treated as
unusable rather than stored, which is the same call the module already makes for a model refusal.
"""


def _caption_all(images: list[bytes]) -> list[str]:
    """Caption every figure concurrently, returning captions in the same order.

    `Runnable.batch` (not a hand-rolled thread pool) so concurrency stays a LangChain
    concern and results stay positionally aligned with the input. `max_concurrency` is
    bounded deliberately -- see the `figure_caption_concurrency` note in config.py. The
    client is built once here rather than per figure, which the previous per-call
    construction did needlessly.

    A failure in any single caption still aborts the whole ingest, exactly as the
    sequential version did -- `batch` re-raises rather than returning partial results.
    Making figure captioning individually fault-tolerant would be a behavior change, not
    a speedup, so it's deliberately left alone here.
    """
    settings = get_settings()
    llm = ChatAnthropic(
        model=settings.figure_caption_model,
        api_key=settings.anthropic_api_key,
        max_tokens=_CAPTION_MAX_TOKENS,
        thinking={"type": "disabled"},
    )
    responses = llm.batch(
        [[_caption_message(image_bytes)] for image_bytes in images],
        config={"max_concurrency": settings.figure_caption_concurrency},
    )
    captions = []
    for response in responses:
        if response.response_metadata.get("stop_reason") == _TRUNCATED_STOP_REASON:
            # Returned empty, which `_is_unusable_caption` drops -- see `_TRUNCATED_STOP_REASON`.
            # A mid-sentence caption is worse than no figure: it becomes the figure's whole
            # retrievable text and reads like a real description.
            log.info("figures.caption_truncated", max_tokens=_CAPTION_MAX_TOKENS)
            captions.append("")
            continue
        captions.append(_response_text(response))
    return captions


def _caption_path(output_dir: Path, image_bytes: bytes) -> Path:
    """Where a caption is cached: keyed on a digest of the image it describes.

    **Not** on `figure_id`, which is what the first version of this cache did and which was
    wrong in the one way that matters. `figure_id` is `fig-{page}-{index}` with `index`
    enumerating every picture item, so inserting a picture earlier in a document shifts every
    later index down onto an id an *earlier* figure already occupied. Nothing deletes stale
    entries, so that is a cache **collision**, not a miss: measured, a newly-inserted figure
    was handed the caption written for the figure that used to hold its id. A caption is a
    figure's only searchable text, so the result is a chunk that describes a different picture
    and reads as perfectly good content -- rule 11's fluent, confident, wrong answer.

    Content addressing removes the class of bug rather than the instance. Byte-identical images
    share a caption, which is also a better hit rate (a figure that merely moved still hits),
    and any change to the pixels misses. The digest is of the PNG this module encoded, not of
    the source file, so it also changes if Docling's rendering changes -- which is exactly when
    a re-caption is wanted.
    """
    return output_dir / f"caption-{hashlib.sha256(image_bytes).hexdigest()[:32]}.txt"


def _cached_caption(path: Path) -> str | None:
    """A usable cached caption, or None -- which means "not cached", for any reason.

    Three failures all have to read as a miss, because the alternative in each case is worse
    than paying for one vision call:

    - **Empty file.** `write_text` is not atomic, so an interrupted write or a full disk leaves
      a zero-byte entry. Read back as `""`, that is dropped by `_is_unusable_caption` and logged
      as `figures.dropped_unusable_caption` -- indistinguishable from a model refusal, and it
      never self-heals, so one bad write suppresses that figure from search permanently.
    - **Undecodable bytes.** A corrupt entry raised `UnicodeDecodeError` out of
      `extract_figures` and failed the whole document's ingest.
    - **Unreadable file.** Permissions, a vanished directory.

    The cost is that a model that genuinely returns an empty caption is re-billed on every
    ingest. That is the right side to err on: the figure is dropped either way, and this way it
    can recover.
    """
    try:
        cached = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None  # An ordinary miss. Silent, or every first ingest logs once per figure.
    except (OSError, UnicodeDecodeError):
        log.info("figures.caption_cache_unreadable", path=str(path))
        return None
    return cached or None


def _store_caption(path: Path, caption: str) -> None:
    """Write a caption to the cache atomically, and never fail the ingest over it.

    Temp file plus `replace`, so a reader never observes a partial write -- see `_cached_caption`
    for what a truncated entry costs.

    The temp name carries the pid and a random suffix, **not** `path.with_suffix(".tmp")`, which
    was the first version. That name is a function of the digest alone, so two writers of the same
    image share it -- and they are reachable: two uploads of identical bytes by one tenant derive
    the same `doc_id`, defer two jobs (see the duplicate-enqueue entry in `docs/IDEAS.md`), and
    `WORKER_CONCURRENCY` defaults to 2. Both would write the same temp path and one would `replace`
    a file the other was still writing, which is the exact failure the temp file exists to prevent.

    `OSError` is swallowed because this is a cache: a full disk should make the next ingest slower,
    not fail this one. Note the narrower truth than the first version of this docstring claimed --
    on a *read-only* mount the document fails earlier anyway, at `output_dir.mkdir` or at the PNG
    write, neither of which is guarded. This guard covers the disk filling up between those and
    here.
    """
    temporary = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(caption, encoding="utf-8")
        temporary.replace(path)
    except OSError:
        log.warning("figures.caption_cache_write_failed", path=str(path))
        temporary.unlink(missing_ok=True)


def _cached_or_captioned(rendered: list[tuple[str, int, Path, bytes]], output_dir: Path) -> list[str]:
    """Captions for every rendered figure, calling the vision model only for the uncached ones.

    Re-ingesting a document was free of Docling work -- `_parse_and_chunk` caches the parsed
    JSON -- but not free of Anthropic work: every figure was re-captioned on every ingest, and
    re-ingest is not rare. It happens on a re-upload of the same file (`doc_id` is a content
    hash of the tenant and the bytes, so the same tenant re-uploading identical content lands on
    the *same* document), and on any retry of a failed job. A 30-figure paper therefore paid 30
    vision calls each time to arrive at the same captions.

    See `_caption_path` for the key, which is the part that was wrong the first time.

    The **raw** model output is cached, before `_is_unusable_caption` runs. Caching only the
    captions that survived would re-bill exactly the figures the model had already refused to
    describe -- the icons and rules, which are also the most numerous.
    """
    captions: list[str] = []
    fresh_indices: list[int] = []
    for index, (_figure_id, _page_no, _image_path, image_bytes) in enumerate(rendered):
        cached = _cached_caption(_caption_path(output_dir, image_bytes))
        captions.append(cached or "")
        if cached is None:
            fresh_indices.append(index)

    if len(fresh_indices) < len(rendered):
        log.info("figures.caption_cache_hit", count=len(rendered) - len(fresh_indices), total=len(rendered))
    if not fresh_indices:
        return captions

    # Deduplicated by digest *within* this batch, not only against the cache on disk. The first
    # version collected every miss and sent them all, so a logo repeated on ten pages cost ten
    # vision calls on the document's first ingest -- while the docstring and a test both claimed
    # one. Worse than the cost: ten independent captions for one image, since the model is
    # non-deterministic, so ten chunks described the same picture differently and a later
    # re-ingest collapsed them onto whichever was written last.
    first_index_of: dict[Path, int] = {}
    for index in fresh_indices:
        first_index_of.setdefault(_caption_path(output_dir, rendered[index][3]), index)

    distinct = list(first_index_of.items())
    new_captions = _caption_all([rendered[index][3] for _path, index in distinct])
    fresh_by_path: dict[Path, str] = {}
    for (path, _index), caption in zip(distinct, new_captions, strict=True):
        fresh_by_path[path] = caption
        _store_caption(path, caption)
    # Fanned out from memory, so every duplicate gets the one caption that was paid for -- and
    # deliberately not by re-reading the cache, which would lose the caption entirely whenever the
    # write failed. `_store_caption` swallows `OSError` precisely so a cache problem does not
    # affect this document; reading back would have undone that.
    for index in fresh_indices:
        captions[index] = fresh_by_path[_caption_path(output_dir, rendered[index][3])]
    return captions


def _is_too_small(image: Image.Image) -> bool:
    """True for images no larger than a glyph in either dimension.

    Docling's `PictureItem` is any embedded image region, so contact icons, logos and decorative
    rules arrive here indistinguishable from charts. Skipping them saves a vision call each and,
    more importantly, keeps them out of the index -- an icon has no describable content, so its
    "caption" is noise competing with real chunks at retrieval time.
    """
    return min(image.size) < get_settings().figure_min_dimension_px


def _is_unusable_caption(caption: str) -> bool:
    """True when a caption cannot serve as searchable text.

    Either the model reported it had nothing to describe (the prompt's sentinel), produced one of
    the familiar can't-see-the-image responses, or returned something too short to be a
    description. Storing any of those gives the figure a chunk whose embedded text is about the
    model's confusion rather than the document.
    """
    lowered = caption.casefold()
    if any(marker in lowered for marker in _UNUSABLE_CAPTION_MARKERS):
        return True
    return len(caption.strip()) < get_settings().figure_min_caption_chars


def extract_figures(document: DoclingDocument, output_dir: Path) -> list[ExtractedFigure]:
    """Save every picture region already rendered in `document` to a PNG and caption it.

    Figures are dropped at two points -- too small to be worth captioning, and captioned but
    unusably. Neither drop renumbers anything: see the comment on `index` below.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    picture_items = [item for item, _level in document.iterate_items() if isinstance(item, PictureItem)]

    # Render and save first, caption second, so all the network calls can go out together.
    # `index` still comes from enumerate over *every* picture item, so an item that is skipped --
    # no renderable image, or too small -- keeps consuming its index: figure_id feeds chunk_id,
    # which feeds the Qdrant point id, so renumbering figures here would orphan every
    # already-stored figure chunk instead of upserting over it.
    rendered: list[tuple[str, int, Path, bytes]] = []
    skipped_small = 0
    for index, item in enumerate(picture_items):
        image = item.get_image(document)
        if image is None:
            continue
        if _is_too_small(image):
            skipped_small += 1
            continue
        provenance = item.prov[0] if item.prov else None
        page_no = provenance.page_no if provenance else 0

        figure_id = f"fig-{page_no:03d}-{index:02d}"
        image_path = output_dir / f"{figure_id}.png"

        # Encoded once, then written. It used to be encoded twice -- once via `image.save(path)`
        # and once into a buffer for the vision call -- which is PNG compression run twice per
        # figure for two byte strings that must be identical. They must be, now more than before:
        # the caption cache keys on this digest, so a second encode that differed at all (a
        # library upgrade changing the default compression level would do it) would miss the
        # cache for every figure while looking like it worked.
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        image_bytes = buffer.getvalue()
        image_path.write_bytes(image_bytes)
        rendered.append((figure_id, page_no, image_path, image_bytes))

    if skipped_small:
        log.info("figures.skipped_small", count=skipped_small, min_dimension=get_settings().figure_min_dimension_px)

    if not rendered:
        return []

    captions = _cached_or_captioned(rendered, output_dir)

    figures: list[ExtractedFigure] = []
    dropped: list[str] = []
    for (figure_id, page_no, image_path, _), caption in zip(rendered, captions, strict=True):
        if _is_unusable_caption(caption):
            dropped.append(figure_id)
            continue
        figures.append(ExtractedFigure(figure_id=figure_id, page_no=page_no, image_path=image_path, caption=caption))

    if dropped:
        # Logged, not raised: one undescribable image should not fail a document. But it must be
        # visible, because the symptom otherwise is a chunk count that quietly disagrees with the
        # figure count.
        log.info("figures.dropped_unusable_caption", figure_ids=dropped, count=len(dropped))

    return figures
