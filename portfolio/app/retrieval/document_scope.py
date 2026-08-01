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

The matching rule is narrow on purpose: **a token in the question must equal a full
filename, extension included.** The looser alternatives all fail badly. Matching bare stems
means a tenant owning `data.pdf` has "what data does the study use?" silently narrowed to
that one file -- a wrong answer with no error, which is the worst failure this system has.
Requiring the extension makes the trigger something a user types deliberately, usually by
copying it out of `GET /v1/documents`.

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

__all__ = ["DocumentScope", "mentions_a_filename", "resolve_scope"]

# Built from the same extension set uploads are validated against, so a format that becomes
# ingestible becomes namable in the same commit. Sorted longest-first because the regex
# alternation is first-match-wins: without it, `doc.tar.gz`-style names ending in a shorter
# extension that prefixes a longer one would match the short one.
_EXTENSION_ALTERNATION = "|".join(re.escape(ext) for ext in sorted(SUPPORTED_UPLOAD_EXTENSIONS, key=len, reverse=True))

# `[\w.\-]+` rather than `\S+` so trailing punctuation ("about report.pdf?") is not swallowed
# into the token. The trailing boundary stops `report.pdfx` matching as `report.pdf`.
_FILENAME_TOKEN = re.compile(rf"[\w.\-]+\.(?:{_EXTENSION_ALTERNATION})\b", re.IGNORECASE)


def mentions_a_filename(question: str) -> bool:
    """Cheap pre-check so the hot path does not pay for a registry read it does not need.

    `/ask` is the highest-traffic route and most questions name no document at all, so
    fetching the tenant's rows unconditionally would add a query per request for nothing.
    This is a regex over the question and touches no I/O; only a `True` justifies the read.
    """
    return _FILENAME_TOKEN.search(question) is not None


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
    """Match filename-shaped tokens in `question` against `records`.

    `records` must already be tenant-scoped -- pass the output of
    `registry.db.list_document_records`. This function does no authorization of its own and
    must never be handed the full table: it would happily scope a query to another tenant's
    `doc_id`, and the Qdrant filter would then AND that against the tenant condition and
    return nothing, which reads as "document is empty" rather than as a leak. Correct, but
    only by accident -- keep the tenant filter upstream where it is legible.
    """
    # The extension alternation is non-capturing, so `findall` yields whole matches.
    tokens = _FILENAME_TOKEN.findall(question)
    if not tokens:
        return DocumentScope()

    by_name = {record.filename.casefold(): record for record in records if record.filename}

    doc_ids: list[str] = []
    filenames: list[str] = []
    unknown: list[str] = []
    for token in dict.fromkeys(tokens):  # de-duplicate, preserve order
        record = by_name.get(token.casefold())
        if record is None:
            unknown.append(token)
        elif record.doc_id not in doc_ids:
            doc_ids.append(record.doc_id)
            filenames.append(record.filename)

    return DocumentScope(doc_ids=doc_ids, filenames=filenames, unknown=unknown)
