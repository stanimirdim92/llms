"""Download the Epic 2 eval corpus into `data/eval/corpus/`, verifying every byte against the manifest.

    uv run python scripts/fetch_eval_corpus.py             # fetch and verify
    uv run python scripts/fetch_eval_corpus.py --record    # fetch and write the digests (bootstrap)

The PDFs are not committed. `data/eval/corpus_manifest.json` is, and it pins each paper by a
**versioned** arXiv id and a sha256 of its bytes -- the two together are what make the golden
set's chunk ids mean anything, because a chunk id is a function of the document's bytes
(`upload_doc_id`) and of where the chunker split them.

This is the successor to the deleted `scripts/fetch_corpus.py`, which fetched the *unversioned*
id and recorded no digest. Both of those were fine for a demo corpus and are not fine for a
measurement fixture: an unversioned id serves whatever revision arXiv currently holds, so a
paper revised upstream would re-chunk differently and every golden chunk id pointing into it
would move to some other passage -- with nothing failing, because a chunk id that no longer
exists just scores as a miss. The digest makes that arrive as an error instead.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "eval"
MANIFEST_PATH = EVAL_DIR / "corpus_manifest.json"
CORPUS_DIR = EVAL_DIR / "corpus"

_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
"""Versioned id, so the URL itself is immutable -- `2008.10896v2`, never `2008.10896`.

arXiv serves both. The unversioned form redirects to the latest revision, which is the property
the old corpus script relied on and the property a fixture must not have.
"""

_REQUEST_SPACING_SECONDS = 3.0
"""Matches the `arxiv` client's own default, which its docstring ties to arXiv's Terms of Use.

Nothing on our side enforces it; the failure mode of ignoring it is a block on the host's terms
rather than a traceback, which is exactly why it is written down rather than remembered.
"""

_ATTEMPTS = 3
"""Tries per paper for a *transient* failure -- a 5xx, a reset, a timeout. A 4xx is permanent
(a withdrawn or mistyped id) and is raised on the first attempt rather than retried.
"""


class CorpusDigestError(RuntimeError):
    """The bytes fetched are not the bytes the manifest pins.

    Loud and fatal, per rule 7 and rule 11. The tempting alternative -- warn and carry on with
    whatever arrived -- produces a corpus that no longer matches `chunk_manifest.json`, and the
    symptom is a drop in recall@k that reads as a retrieval regression. The recovery is
    deliberate work (re-record the digest, rebuild the chunk manifest, re-check every golden
    pair that referenced the changed document), not a flag.
    """


def _download(client: httpx.Client, arxiv_id: str) -> bytes:
    last: httpx.HTTPError | None = None
    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(_REQUEST_SPACING_SECONDS)
        try:
            response = client.get(_PDF_URL.format(arxiv_id=arxiv_id))
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.is_client_error:
                raise
            last = exc
            continue
        except httpx.HTTPError as exc:
            last = exc
            continue
        return response.content
    assert last is not None
    raise last


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_cached(target: Path, expected: str | None) -> bool:
    """By digest, never by existence -- a truncated file from an interrupted run exists too."""
    return bool(expected) and target.exists() and _digest(target.read_bytes()) == expected


def _verified_digest(arxiv_id: str, data: bytes, expected: str | None, *, record: bool) -> str:
    """The digest of bytes that are allowed to reach disk. Raises on anything else.

    Both refusals happen *before* the write, so a rejected paper leaves nothing behind. An
    unpinned or mismatched PDF sitting in the corpus directory is the state this exists to
    prevent: the next run chunks it, and the ids it produces look exactly as real as pinned ones.
    """
    actual = _digest(data)
    if expected and actual != expected:
        msg = (
            f"{arxiv_id} does not match the manifest: expected sha256 {expected}, fetched "
            f"{actual} ({len(data)} bytes). arXiv is serving different bytes for a versioned id, "
            f"or the manifest is wrong. Refusing to write, because every chunk id in "
            f"chunk_manifest.json is derived from these bytes."
        )
        raise CorpusDigestError(msg)
    if expected is None and not record:
        msg = (
            f"{arxiv_id} has no sha256 in the manifest. Run with --record to pin the bytes that "
            f"were just fetched ({actual})."
        )
        raise CorpusDigestError(msg)
    return actual


def fetch(*, record: bool) -> int:
    """Fetch every paper. Returns a process exit code.

    A paper already on disk with the right digest is not re-fetched, so a rerun costs nothing
    and does not hit arXiv at all.
    """
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    changed = False

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        for index, paper in enumerate(manifest["papers"]):
            arxiv_id = paper["arxiv_id"]
            target = CORPUS_DIR / paper["filename"]
            expected = paper["sha256"]

            if _is_cached(target, expected):
                print(f"ok (cached)   {arxiv_id}")
                continue

            if index:
                time.sleep(_REQUEST_SPACING_SECONDS)
            try:
                data = _download(client, arxiv_id)
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                # `InvalidURL` is not an `HTTPError` subclass, so it has to be named here or it
                # escapes and stops the whole fetch on one malformed manifest entry.
                failures.append(f"{arxiv_id}: {exc}")
                print(f"FAILED        {arxiv_id}: {exc}")
                continue

            actual = _verified_digest(arxiv_id, data, expected, record=record)
            target.write_bytes(data)
            if expected is None:
                paper["sha256"] = actual
                paper["bytes"] = len(data)
                changed = True
            print(f"ok            {arxiv_id}  {len(data)} bytes  {actual[:12]}...")

    if changed:
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"recorded digests in {MANIFEST_PATH}")

    if failures:
        print(f"\n{len(failures)} paper(s) could not be fetched:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="write the fetched digests into the manifest for papers that have none (bootstrap only)",
    )
    return fetch(record=parser.parse_args().record)


if __name__ == "__main__":
    raise SystemExit(main())
