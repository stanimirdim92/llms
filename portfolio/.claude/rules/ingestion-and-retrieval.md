---
paths:
  - "**/app/ingestion/**"
  - "**/app/worker/**"
  - "**/app/retrieval/**"
  - "**/app/vectorstore/**"
  - "**/app/registry/**"
  - "**/app/generation/**"
  - "**/app/api/routers/ask.py"
  - "**/app/api/routers/documents.py"
  - "**/streamlit_app/**"
  - "**/tests/unit/test_ingest_failures.py"
  - "**/tests/unit/test_qdrant_filtering.py"
  - "**/tests/unit/test_retrieval_consistency.py"
  - "**/tests/unit/test_upload_paths.py"
  - "**/tests/unit/test_figure_ids.py"
---

# Ingestion, the vector store and retrieval

Path-scoped: loads when a matching file is read. The general rules (`../CLAUDE.md`) and the
cross-cutting contracts (`CLAUDE.md` § Never, § The tenant boundary) still apply.

## Never

- **Postgres decides what is searchable; Qdrant cannot.** `ingest_document` inserts a generation's
  points and *then* flips the registry row, so a failure between them leaves points that are stored
  and unreadable. `Retriever.retrieve` filters on `list_active_versions`, passing **both** the
  permitted `doc_ids` and the live `versions` into the filter, and it does so **in the retriever**
  rather than the router because `/ask` and Streamlit both arrive there -- a check in one caller is a
  check the other forgets.
  **An empty permitted set must return no results, never fall through to an unfiltered search**:
  `_build_filter` used `if doc_ids:`, so `[]` meant "no document condition at all". It now raises on
  an empty `doc_ids` *and* an empty `versions`, and `tests/unit/test_retrieval_consistency.py` pins
  every half. The `versions` guard is the harder one to test honestly -- `MatchAny(any=[])` returns
  zero points, so an empty list is accidentally safe, while the mutation that matters (`if versions:`)
  emits no condition at all. Assert the raise, not the engine's answer.
- **Never make `QdrantStore.upsert` delete anything.** It inserts one generation, whose
  `ingestion_version` is hashed into every point id (`uuid5(ns, f"{version}:{chunk_id}")`), and
  publication is `activate_document_version`'s single UPDATE. Pruning is `delete_superseded`, called
  after the flip and allowed to fail.

  This replaced delete-then-insert, and the old contract said the exact opposite -- so re-adding a
  delete here looks like restoring a safeguard. It is not. Deleting first made a document's
  correctness depend on the *next* statement succeeding: a landed delete plus a failed insert left a
  working document with no points while its row still said `ingested`, so retrieval permitted the
  `doc_id`, found nothing, and an unscoped question was answered from the tenant's other documents
  with no indication. Chunk ids encode position (`{doc_id}-text-0000`, `fig-{page}-{index}`), so
  anything changing how many chunks a document yields (`chunk_max_tokens`, a Docling upgrade
  detecting one more figure) still shifts every later id -- the version in the point id is what makes
  that harmless now, rather than the delete.

  Three consequences to keep: the flip must publish **the version that was upserted** (a second
  `new_id()` there publishes a generation with no points in it); a failed flip must **not** prune,
  because `delete_superseded` removes every version *except* the one it keeps and would delete the
  generation still serving; and a failed prune must **not** fail the ingest, because the leftovers
  are already unreadable. `tests/unit/test_ingest_failures.py` and `test_qdrant_filtering.py` pin all
  three, each mutation-confirmed red.
- **`stage_document_record` does not commit; `save_document_record` does. Streamlit needs the
  second one.** The distinction is invisible from inside the writing session -- SQLAlchemy shows the
  row on its own connection either way -- so it can only be tested from a *second* session, and
  `test_the_two_row_writers_differ_only_in_whether_they_commit` is where that lives. Streamlit called
  the staging variant for one commit's worth of time: its `pending` row was rolled back when the
  session closed, and by the time the flip raised `DocumentNotFoundError` the generation was already
  in Qdrant, orphaned. **The API path was unaffected**, because it commits explicitly after deferring
  the job -- which is why nothing caught it.
  **Streamlit is the one write path with no test**, so a reverse search over it proves less than it
  looks: `save_document_record` was deleted the same morning as "no production caller", and the
  caller existed -- it was the broken one. A function whose only callers are tests can mean a broken
  caller, not a dead function.
- **Never put a document's bytes at a path the filename alone determines.** `document_upload_path`
  gives `<root>/<tenant_id>/<doc_id>/<safe filename>`, and `doc_id` is in there because two
  documents sharing a filename otherwise share a path: worker A reads B's bytes, files B's content
  under A's `doc_id`, and records B's `content_hash` as A's, so **nothing afterwards looks wrong**.
  It is sticky rather than transient -- the parse cache is `processed_dir/<doc_id>.json` and figures
  are `processed_dir/<doc_id>/figures`, so a later correct re-ingest reads the poisoned cache.
  Both writers must use that helper (the router *and* Streamlit, which had its own copy of the bug),
  and `write_upload`'s rename is what stops a worker reading a half-written file.
  **`expected_digest` is the second line and must stay fail-closed**, checked *before* the parse —
  after it, the wrong bytes are already cached under this id. `tests/unit/test_upload_paths.py`
  pins all of it; three mutations were confirmed red, including moving the check after the parse.
- **Never renumber figure ids** in `figure_extractor.extract_figures`. A picture item with no
  renderable image still consumes its `enumerate` index on purpose;
  `tests/unit/test_figure_ids.py` pins this. `figure_id` feeds `chunk_id`, which feeds the point id,
  so a shift churns every citation the document has ever produced.
  **Everything addressed by a figure id must therefore also be addressed by its content.** The
  caption cache is (`caption-<sha256>.txt`, after being handed the caption written for whichever
  figure previously held its id) and, since 2026-08-06, so is the PNG: `_image_path` is
  `<figure_id>-<sha256[:16]>.png`. It was `<figure_id>.png`, overwritten in place by the next
  ingest, which was survivable only while a re-ingest deleted the old chunks at the same moment.
  Versioned ingestion makes "the previous generation keeps serving" the designed fallback, and the
  image files do not roll back with it -- so a position-addressed path left a live chunk citing a
  file that now held a different picture, which `streamlit_app/Home.py` renders directly beside the
  old caption.

## Failure contracts

- **Qdrant point IDs must be an unsigned integer or a UUID.** Chroma accepted
  arbitrary strings; Qdrant rejects a `chunk_id` with a 400. Hence the uuid5
  derivation above. `chunk_id` itself stays in the payload metadata -- citations
  read it from there, never from the point ID.
- **Qdrant filters must be real `qdrant_client.models.Filter` objects.** The
  Mongo-style dict shorthand (`$in`/`$and`) only ever existed on the deprecated
  `Qdrant` class. Getting this wrong doesn't error -- it silently breaks tenant
  scoping, leaking one tenant's uploads into another tenant's results.
- **`QdrantVectorStore` has no native async client.** `asimilarity_search` is
  `VectorStore`'s thread-pool shim and `upsert` is sync. That's why
  `ingest_document` offloads through `asyncio.to_thread` instead of just being
  `async def`.
- **`chunk_document`'s returned list is not document reading order.** It emits every text
  chunk, then every table chunk, then every figure chunk -- each internally ordered but not
  interleaved with the others, because text goes through `HybridChunker` (which merges
  granular items into semantic windows) while tables and figures are kept atomic, and the
  three cannot share one loop without giving that up. A table on page 3 therefore sits after
  every text chunk in the whole document in this list. `Chunk.order_index`
  (`app/ingestion/document_order.py::document_order_map`, computed once from
  `document.iterate_items()`) is what `QdrantStore.get_document_chunks` sorts on to
  reconstruct a document for viewing -- sorting or rendering the *list* itself silently
  reproduces the grouped-by-kind bug this exists to fix.
- **Docling parsing is CPU-bound.** Wrapping it in `async def` does not free the
  event loop; it has to go through `asyncio.to_thread` or one upload stalls every
  other request on that worker.

- **A figure's caption is its only searchable text**, so an unusable caption is worse than
  no figure. Docling reports every embedded image region as a `PictureItem` -- contact icons,
  logos, horizontal rules -- indistinguishable from a chart. A one-page CV produced five
  "figures", all ~20x20px icons; the vision model answered each with "I'm not able to see the
  image you're referring to", and those refusals became chunks that then won reranking and
  became what an answer was grounded in. `figure_extractor` therefore drops images below
  `figure_min_dimension_px` *before* the vision call and captions matching
  `_UNUSABLE_CAPTION_MARKERS` (or shorter than `figure_min_caption_chars`) after it. Both drops
  must preserve the `enumerate` index -- see the "never renumber" rule above.
- **A successful parse does not mean an ingestible document.** A scanned, image-only PDF
  parses fine and yields no text: a real 2MB flyer extracted 30 characters with `do_ocr=False`
  versus 395 with it on. Recording that as `ingested` with `chunk_count=0` is a lie the user
  can only discover by asking a question and getting someone else's document back, so
  `ingest_document` raises `EmptyDocumentError` instead.

## Qdrant payload indexes

**The one finding the qdrant set produced is closed** (2026-08-03): `qdrant_store._ensure_payload_indexes` indexes
`metadata.tenant_id` with **`is_tenant=True`** and `metadata.doc_id` as a plain keyword, from
`QdrantStore.__init__`. **`is_tenant` is not a synonym for "indexed"** -- it tells Qdrant the
field identifies tenants, so a tenant's vectors are stored together and a tenant-filtered
search is served by sequential reads rather than degrading toward a scan at the 10k-tenant x
10-document target. Don't drop the flag while keeping the index and assume it is equivalent.
`metadata.chunk_type` is deliberately *not* indexed (no production caller passes `chunk_types`).
Details in `.claude/skills/VENDORED.md`.
