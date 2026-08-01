"""Recognise a filename named inside a free-text question and narrow retrieval to it.

Asked "give me the contents of 3020072D.pdf", the answer path previously searched the
tenant's whole corpus and assembled a reply from whatever ranked highest -- so the response
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
  `{tenant_id}-{hash}` shape that `upload_doc_id` generates. The marker is what makes the
  curated corpus's ids usable at all: those are bare arXiv ids like `2008.10896`, which no
  regex can distinguish from a decimal number in running prose.

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
guessing helps more than it hurts. See `EPIC_2_PLAN.md`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.ingestion.formats import SUPPORTED_UPLOAD_EXTENSIONS

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

# An explicit marker, so *any* id shape works -- including the curated corpus's bare arXiv
# ids, which are unmatchable on shape alone. Accepts what people actually type: `doc_id=x`,
# `doc id: x`, `docid = x`.
_DOC_ID_MARKER = re.compile(r"\bdoc[_\s-]?id\s*[=:]\s*([^\s,;]+)", re.IGNORECASE)

# The shape `upload_doc_id` generates: `{tenant_id}-{sha256[:32]}`, where tenant_id is a
# `uuid7().hex` or the literal `global` for the shared corpus. Matched bare so an id pasted
# straight out of `GET /v1/documents` works without the marker. Two fixed-length hex runs are
# specific enough not to collide with prose; a bare arXiv id deliberately is not.
_DOC_ID_SHAPE = re.compile(r"\b(?:[0-9a-f]{32}|global)-[0-9a-f]{32}\b", re.IGNORECASE)


def mentions_a_document(question: str) -> bool:
    """Cheap pre-check so the hot path does not pay for a registry read it does not need.

    `/ask` is the highest-traffic route and most questions name no document at all, so
    fetching the tenant's rows unconditionally would add a query per request for nothing.
    This is three regexes over the question and touches no I/O; only a `True` justifies the
    read. It must stay in sync with what `resolve_scope` looks for -- a token this misses is
    a token that silently never scopes, which is how naming a `doc_id` came to be ignored.
    """
    return any(pattern.search(question) for pattern in (_FILENAME_TOKEN, _DOC_ID_MARKER, _DOC_ID_SHAPE))


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

    @property
    def is_scoped(self) -> bool:
        return bool(self.doc_ids)

    @property
    def names_nothing_owned(self) -> bool:
        """The question named only documents this tenant does not have."""
        return bool(self.unknown) and not self.doc_ids


def resolve_scope(question: str, records: list[DocumentRecord]) -> DocumentScope:
    """Match filename- and doc_id-shaped tokens in `question` against `records`.

    `records` must already be tenant-scoped -- pass the output of
    `registry.db.list_document_records`. This function does no authorization of its own and
    must never be handed the full table: it would happily scope a query to another tenant's
    `doc_id`, and the Qdrant filter would then AND that against the tenant condition and
    return nothing, which reads as "document is empty" rather than as a leak. Correct, but
    only by accident -- keep the tenant filter upstream where it is legible.

    A `doc_id` typed into a question is user input like any other and gets the same treatment
    as a filename: it resolves only if it is in this caller's own rows. That is what makes
    accepting it safe, since a `doc_id` embeds a tenant prefix and would otherwise look
    authoritative enough to trust.
    """
    # Both id patterns are non-capturing except the marker's single group, so `findall`
    # yields the token itself in every case.
    tokens = [
        *_FILENAME_TOKEN.findall(question),
        *_DOC_ID_MARKER.findall(question),
        *_DOC_ID_SHAPE.findall(question),
    ]
    if not tokens:
        return DocumentScope()

    by_name = {record.filename.casefold(): record for record in records if record.filename}
    # doc_id wins on collision, but the keyspaces cannot overlap in practice: every filename
    # match carries a supported extension and no doc_id shape ends in one.
    by_id = {record.doc_id.casefold(): record for record in records}

    doc_ids: list[str] = []
    filenames: list[str] = []
    unknown: list[str] = []
    for token in dict.fromkeys(tokens):  # de-duplicate, preserve order
        record = by_id.get(token.casefold()) or by_name.get(token.casefold())
        if record is None:
            unknown.append(token)
        elif record.doc_id not in doc_ids:
            doc_ids.append(record.doc_id)
            # The filename is what `scoped_to` reports, so a document named by id is still
            # echoed back by name -- the id tells the user nothing they didn't just type.
            filenames.append(record.filename or record.doc_id)

    return DocumentScope(doc_ids=doc_ids, filenames=filenames, unknown=unknown)
