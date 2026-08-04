"""Recognise a filename named inside a free-text question and narrow retrieval to it.

Asked "give me the contents of 3020072D.pdf", the answer path previously searched the
tenant's whole collection and assembled a reply from whatever ranked highest -- so the response
could be about a different document entirely, stated confidently. Naming a document is a
*scoping* instruction, and scoping is not a relevance problem.

**Deliberately no model call.** The candidate set is known and small: a tenant's own
documents, read from the registry. So this is string matching against a closed set, not
extraction from open text -- plain code, per the project's rule about reserving the model
for judgment calls. It is also fully unit-testable with no services and no API keys, which
a classifier would not be.

Two things count as naming a document, because both are things a user copies out of
`GET /v1/documents`:

- **A full filename, extension included.** The looser alternatives all fail badly. Matching
  bare stems means a tenant owning `data.pdf` has "what data does the study use?" silently
  narrowed to that one file -- a wrong answer with no error, which is the worst failure this
  system has. Requiring the extension makes the trigger deliberate.
- **A `doc_id`**, either behind an explicit `doc_id=` marker or as the bare
  `{tenant_id}-{hash}` shape that `upload_doc_id` generates. The marker exists so an id of
  *any* shape can be named, including shapes no regex can safely match bare -- a bare
  `2008.10896` is indistinguishable from a decimal number in running prose. Every id minted
  today has the two-hex-run shape, so the marker is currently belt to the pattern's braces;
  it stays because it is documented API surface and because the next id scheme need not be
  as convenient.

Ignoring ids was a real defect, not a hypothetical. Asked for structured output "for document
with id ... doc_id=019fb3...", the search ran unscoped and four of the five chunks that won
reranking came from the tenant's CV rather than the named advertisement -- the question was
mostly Pydantic field descriptions ("The name of the company or entity", "the phone number,
formatted for international dialling"), which embed far closer to a CV's contact and profile
sections than to a sparse one-page flyer.

Two outcomes besides a match, both of which the caller must surface rather than swallow:

- The question names a filename-shaped token that the tenant does not own. Searching
  everything anyway produces a confident answer about the wrong document; the honest reply
  is that no such document exists, with a list of what does.
- The question names nothing. Ordinary unscoped retrieval, unchanged.

What this deliberately does *not* handle is a semantic reference -- "the flyer", "my CV",
"the German one". That genuinely needs a model, and it needs the eval harness to show the
guessing helps more than it hurts. See `docs/EPIC_2_PLAN.md`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS
from app.registry.models import STATUS_INGESTED

if TYPE_CHECKING:
    from app.registry.models import DocumentRecord

__all__ = ["DocumentScope", "mentions_a_document", "resolve_scope"]

# Built from the same extension set uploads are validated against, so a format that becomes
# ingestible becomes namable in the same commit. Sorted longest-first because the regex
# alternation is first-match-wins: without it, `doc.tar.gz`-style names ending in a shorter
# extension that prefixes a longer one would match the short one.
_EXTENSION_ALTERNATION = "|".join(re.escape(ext) for ext in sorted(SUPPORTED_UPLOAD_EXTENSIONS, key=len, reverse=True))

# `[\w.\-]+` rather than `\S+` so trailing punctuation ("about report.pdf?") is not swallowed
# into the token. The trailing boundary stops `report.pdfx` matching as `report.pdf`.
_FILENAME_TOKEN = re.compile(rf"[\w.\-]+\.(?:{_EXTENSION_ALTERNATION})\b", re.IGNORECASE)

# An explicit marker, so *any* id shape works -- including shapes unmatchable on shape alone.
# Accepts what people actually type: `doc_id=x`, `doc id: x`, `docid = x`.
_DOC_ID_MARKER = re.compile(r"\bdoc[_\s-]?id\s*[=:]\s*([^\s,;]+)", re.IGNORECASE)

# Trailing characters the capture above swallows that are never part of an id: a
# sentence-ending period, a closing quote or bracket. Without this, `doc_id=<id>.` and
# `doc_id="<id>"` both fail to match a stored id and 404 on a document that exists -- fails
# closed, but on the form the API docs tell callers to use.
_ID_EDGE_NOISE = "\"'`.,;:!?)]}>"

# A candidate token only counts as an id if it contains a digit -- applied to bare `_DOC_ID_SHAPE`
# matches as well as to marker captures, though only the marker form is loose enough for it to
# matter. Every id this project mints is `{32 hex}-{32 hex}`, so "contains a digit" rather than
# "starts with" one: either run can in principle be digit-free hex, which is vanishingly unlikely
# ((6/16)^32) but not impossible, so this is a heuristic and not a guarantee. Prose does not:
# a question quoting SQL -- "why does `WHERE doc_id = 'x'` return nothing?" -- or a template
# (`doc_id=%(doc_id)s`) used to be read as naming a document, fail to match any row, and refuse
# the entire question with a 404 that named a document the user had not asked about. Refusing
# rather than answering is right when a document *was* named (rule 11); this is about not
# hallucinating that one was.
_ID_MUST_CONTAIN_A_DIGIT = re.compile(r"\d")

# The shape `upload_doc_id` generates: `{tenant_id}-{sha256[:32]}`, where tenant_id is a
# `uuid7().hex`. Matched bare so an id pasted straight out of `GET /v1/documents` works without
# the marker. Two fixed-length hex runs are specific enough not to collide with prose.
#
# The `|global` alternative that used to sit in this pattern went with the shared corpus. It was
# there because corpus documents were tagged `global`, so their ids were `global-{32 hex}` -- a
# shape no tenant can produce now, since `global` is not a `uuid7().hex`.
_DOC_ID_SHAPE = re.compile(r"\b[0-9a-f]{32}-[0-9a-f]{32}\b", re.IGNORECASE)


_LOOSE_FILENAME = re.compile(rf"\S*\.(?:{_EXTENSION_ALTERNATION})(?!\w)", re.IGNORECASE)
r"""A filename-ish run of non-space characters ending in a supported extension.

Used to report what the caller *named but does not have*, so it has to admit everything the
gate admits -- `\S*` rather than `[\w.\-]*`, because a name with a parenthesis or a quote is
still a name. Over-matching here costs a 404 with a slightly untidy token in the message;
under-matching costs a confident answer about the wrong documents.
"""

_EXTENSION_MENTION = re.compile(rf"\.(?:{_EXTENSION_ALTERNATION})(?!\w)", re.IGNORECASE)
"""Just "an extension appears here", with no constraint on what precedes it.

Deliberately looser than `_FILENAME_TOKEN`. This gate decides only whether a registry read is
worth doing; `resolve_scope` decides what actually matches. Any asymmetry has to fall on the
side of reading too often, because a token the *gate* misses can never be scoped no matter
what the resolver can handle -- and that is not hypothetical. `_FILENAME_TOKEN` cannot cross a
`(`, so after `resolve_scope` learned to match `report(1).pdf`, the gate still returned False
for it and `/ask` ran an unscoped search without ever consulting the registry. The resolver
test passed; the feature did not work.
"""


def mentions_a_document(question: str) -> bool:
    """Cheap pre-check so the hot path does not pay for a registry read it does not need.

    `/ask` is the highest-traffic route and most questions name no document at all, so
    fetching the tenant's rows unconditionally would add a query per request for nothing.
    This is three regexes over the question and touches no I/O; only a `True` justifies the
    read.

    **It must be strictly weaker than what `resolve_scope` can match.** A token this misses is
    a token that silently never scopes -- which is how naming a `doc_id` came to be ignored
    once, and how a parenthesised filename came to be ignored a second time.
    `test_document_scope.py::test_the_gate_admits_everything_the_resolver_can_match` pins the
    relationship rather than trusting this comment.
    """
    return any(pattern.search(question) for pattern in (_EXTENSION_MENTION, _DOC_ID_MARKER, _DOC_ID_SHAPE))


@dataclass(frozen=True)
class DocumentScope:
    """The result of reading a question for document names.

    `doc_ids` empty *and* `unknown` empty means the question named nothing and retrieval
    should run unscoped -- which is not the same as `unknown` being populated, where the
    question named something that does not exist and the caller should refuse instead of
    quietly searching everything.
    """

    doc_ids: list[str] = field(default_factory=list)
    filenames: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    not_ready: list[str] = field(default_factory=list)
    """Documents the caller owns that are named in the question but are not `ingested`.

    Distinguished from `unknown` because the honest answer is different: the document exists,
    it just has no chunks yet (or failed). Scoping to it "succeeds" and returns an empty,
    confident non-answer -- so the caller must say *pending* or *failed*, not *no such
    document*, and certainly not answer from the tenant's other documents.
    """

    @property
    def is_scoped(self) -> bool:
        return bool(self.doc_ids)

    @property
    def names_nothing_owned(self) -> bool:
        """The question named only documents this tenant does not have."""
        return bool(self.unknown) and not self.doc_ids

    @property
    def names_only_unready(self) -> bool:
        """Everything named is owned but not yet searchable."""
        return bool(self.not_ready) and not self.doc_ids and not self.unknown


def _id_tokens(question: str) -> list[tuple[int, str]]:
    """Every `doc_id`-ish token in the question, with where it started.

    The position is what lets `resolve_scope` report matches in the order the user wrote
    them. Marker captures are stripped of `_ID_EDGE_NOISE`; an empty remainder (someone wrote
    a bare `doc_id=.`) is dropped rather than reported as an unknown document.
    """
    tokens = [
        *((match.start(1), match.group(1).strip(_ID_EDGE_NOISE)) for match in _DOC_ID_MARKER.finditer(question)),
        *((match.start(), match.group()) for match in _DOC_ID_SHAPE.finditer(question)),
    ]
    return [(position, token) for position, token in tokens if token and _ID_MUST_CONTAIN_A_DIGIT.search(token)]


def resolve_scope(question: str, records: list[DocumentRecord]) -> DocumentScope:
    """Match filename- and doc_id-shaped tokens in `question` against `records`.

    `records` must already be scoped to what the caller may read -- pass the output of
    `registry.db.list_document_records`, which puts `tenant_id` in the WHERE clause.

    There used to be a second query, `list_scope_candidates`, because the shared corpus made
    "what may I scope to" wider than "what do I own". The corpus is gone and so is that query.
    Worth knowing why it existed: while both existed they disagreed, and the disagreement was a
    404 on every document the API docs told callers to name.

    This function does no authorization of its own and must never be handed the full table:
    it would happily scope a query to another tenant's `doc_id`, and the Qdrant filter would
    then AND that against the tenant condition and return nothing, which reads as "document
    is empty" rather than as a leak. Correct, but only by accident -- keep the entitlement
    filter upstream where it is legible.

    A `doc_id` typed into a question is user input like any other and gets the same treatment
    as a filename: it resolves only if it is in this caller's own rows. That is what makes
    accepting it safe, since a `doc_id` embeds a tenant prefix and would otherwise look
    authoritative enough to trust.
    """
    # Filenames are matched by *substring against the real names*, not by pulling
    # filename-shaped tokens out of the prose. The token regex cannot span a space or a
    # parenthesis, so `Draft Report.pdf` used to yield only `Report.pdf` -- which resolved to
    # a different, real document and answered confidently about the wrong file. Matching the
    # known names against the question inverts that: whatever characters a filename contains,
    # it is found, because the candidate set is closed and small.
    #
    # Longest first, and each match is masked out of the remaining text, so `Report.pdf` does
    # not also fire inside `Draft Report.pdf` and scope to two documents.
    remaining = question
    # (position in the question, record, label) so results come back in the order the user
    # named them rather than in match order -- `scoped_to` echoes this straight back, and
    # longest-first is an implementation detail the caller should never see.
    hits: list[tuple[int, DocumentRecord, str]] = []

    named = sorted((r for r in records if r.filename), key=lambda r: len(r.filename), reverse=True)
    for record in named:
        # Boundaries on both sides: without them `report.pdf` matches inside `myreport.pdf`
        # and inside `report.pdfx`, which is the same class of false positive the token
        # regex's `\b` was there to stop. `(?!\w)` still permits a trailing period, so
        # "summarise report.pdf." works.
        pattern = re.compile(rf"(?<!\w){re.escape(record.filename)}(?!\w)", re.IGNORECASE)
        spans = list(pattern.finditer(remaining))
        if not spans:
            continue
        hits.append((spans[0].start(), record, record.filename))
        # Every occurrence, not just the first. Masking one left the second visible to the
        # leftover scan below, which reported an owned document as `unknown` -- so "does
        # queued.pdf mention X in queued.pdf" 404'd as a document the tenant does not have,
        # and a repeated name matched the older duplicate too, undoing newest-wins.
        for span in reversed(spans):
            remaining = remaining[: span.start()] + " " * (span.end() - span.start()) + remaining[span.end() :]

    # Ids come from the *original* question: masking only removes filename spans, and an id
    # never overlaps one. Marker captures are stripped of trailing punctuation and quotes --
    # see `_ID_EDGE_NOISE`.
    # Newest wins on a duplicate name or id: `records` arrives newest-first, so the *first*
    # occurrence is kept rather than being overwritten by each older one in turn. A tenant who
    # re-uploads a revised `report.pdf` means the new one.
    by_id: dict[str, DocumentRecord] = {}
    for record in records:
        by_id.setdefault(record.doc_id.casefold(), record)

    unknown: list[str] = []
    for position, token in _id_tokens(question):
        if token in unknown:
            continue
        record = by_id.get(token.casefold())
        if record is None:
            unknown.append(token)
        else:
            hits.append((position, record, record.filename or record.doc_id))

    # Anything still *looking* like a filename in the unmasked remainder names a document
    # this caller does not have. Reported rather than ignored: searching everything anyway is
    # the confident-wrong-answer failure this module exists to prevent.
    # `_LOOSE_FILENAME`, not `_FILENAME_TOKEN`. The gate was widened to admit parenthesised
    # names; leaving the *leftover* scan narrow just moved the asymmetry rather than closing
    # it. An unowned `report(1).pdf` produced no token here, so `unknown` stayed empty and the
    # question ran unscoped -- a confident answer assembled from every other document, which
    # is the failure this module exists to prevent, arriving by a different route.
    unknown.extend(token for token in _LOOSE_FILENAME.findall(remaining) if token not in unknown)

    return _classify(hits, unknown)


def _classify(hits: list[tuple[int, DocumentRecord, str]], unknown: list[str]) -> DocumentScope:
    """Split matched records into searchable and not-yet-searchable, in question order.

    Sorted by position so `scoped_to` echoes the order the user named things; longest-first
    matching is an implementation detail the caller should never see.
    """
    doc_ids: list[str] = []
    filenames: list[str] = []
    not_ready: list[str] = []
    for _, record, label in sorted(hits, key=lambda hit: hit[0]):
        if record.status != STATUS_INGESTED:
            if label not in not_ready:
                not_ready.append(label)
        elif record.doc_id not in doc_ids:
            doc_ids.append(record.doc_id)
            filenames.append(record.filename or record.doc_id)
    return DocumentScope(doc_ids=doc_ids, filenames=filenames, unknown=unknown, not_ready=not_ready)
