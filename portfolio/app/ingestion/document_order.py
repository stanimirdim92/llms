"""True document reading order, computed once and shared by chunking and figure extraction.

`chunk_document` groups its output by kind -- every text chunk, then every table chunk, then
every figure chunk, each internally ordered but not interleaved with the others (see that
module's docstring). A chunk's position in the returned list is therefore not its position in
the document: a table on page 3 comes after every text chunk in a 50-page document, not next
to the text around it. Reconstructing a document for viewing needs the real order instead,
which this supplies without disturbing any existing `chunk_id` numbering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docling_core.types.doc.document import DoclingDocument


def document_order_map(document: DoclingDocument) -> dict[str, int]:
    """Maps every item's `self_ref` to its position in `document.iterate_items()`'s traversal.

    That traversal is Docling's own reading order across every item type at once -- text,
    tables, and figures interleaved as they actually appear -- unlike the separate per-type
    passes `chunk_document` and `extract_figures` each run. Calling this twice on the same
    document (once from each of those) returns the same numbers for the same items: the
    traversal is a pure walk of the document's own tree, not something either caller mutates.

    An item this misses (a group or content layer `iterate_items()`'s defaults exclude) is a
    caller decision, not this function's -- callers look up with `.get(ref, <sentinel>)` and
    choose what "not found" should sort as.
    """
    return {item.self_ref: index for index, (item, _level) in enumerate(document.iterate_items())}
