"""Download every PDF listed in data/manifest.json into data/raw_pdfs/, skipping ones already present."""

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings

_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
"""arXiv serves the latest version of a paper at its unversioned id, which is what the
manifest stores. Verified rather than assumed: a HEAD of this URL returns
`200 application/pdf`, with no redirect.

This used to go through the `arxiv` client, purely to resolve `Result.pdf_url` -- and that
dependency is gone. It was already only half in use: `arxiv>=4` removed
`Result.download_pdf`, so the file it named was fetched over plain HTTP regardless.

**But dropping it did lose something**, and an earlier version of this docstring wrongly said it
did not. `arxiv.Client.__init__` defaults to `delay_seconds=3.0` and `num_retries=3`, and its own
docstring warns that shrinking them "risks violating the arXiv API Terms of Use". So the old loop
was paced at one request per 3 seconds with retries; a bare `client.get` loop is back-to-back
multi-MB requests to a public academic host that hard-fails the build on the first 5xx. Invisible
at 6 papers, which is why it went unnoticed -- `data/manifest.json`'s own note says to expand
toward ~45. `_REQUEST_SPACING_SECONDS` and `_ATTEMPTS` below restore both.

One consequence, unchanged either way but worth stating. The id is unversioned, so a revised
paper yields different bytes under the same id -- and since `scripts/ingest.py` uses the arXiv
id as the `doc_id`, that re-ingest correctly *replaces* the document rather than adding a
second copy. `content_hash` in the registry is what records that the bytes moved.
"""

_REQUEST_SPACING_SECONDS = 3.0
"""Matches the `arxiv` client's own default, which its docstring ties to arXiv's Terms of Use.

Kept even though nothing enforces it from our side: the failure mode of ignoring it is a block
on the host's terms rather than an error we would see in a traceback.
"""

_ATTEMPTS = 3
"""Total tries per paper for a *transient* failure -- a 5xx, a reset, a timeout.

In the same range as the `arxiv` client's `num_retries=3`, and deliberately not described as
"matching" it: that client retried 4 times in total (`_try_index < num_retries` starting at 0) and
those retries covered the Atom *metadata* request, never the PDF fetch, which had none.
"""


def _download(client: httpx.Client, arxiv_id: str) -> bytes:
    """The PDF bytes, retrying transient failures.

    Retries only what can succeed on a second try. Two kinds of failure are permanent and are
    raised on the first attempt instead:

    - **A 4xx**, which is what a withdrawn or *mistyped* id actually produces -- an ordinary typo
      is a perfectly valid URL and a 404 from arXiv. The first version of this function retried
      those three times with two 3-second sleeps, directly against the rationale written here.
    - **`httpx.InvalidURL`**, which is **not** a subclass of `HTTPError` (checked against httpx
      0.28.1), so it also has to be named in the caller's per-paper handler or it escapes and stops
      the build. Reachable only from a *non-printable* character -- a stray newline in
      `manifest.json`. `httpx.URL` accepts `abc`, `2008 10896` and `../../etc/passwd` without
      complaint, so the earlier claim that this guard catches a mistyped id was wrong.
    """
    last: httpx.HTTPError | None = None
    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(_REQUEST_SPACING_SECONDS)
        try:
            response = client.get(_PDF_URL.format(arxiv_id=arxiv_id))
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.is_client_error:
                raise  # permanent: a withdrawn or mistyped id, not a blip
            last = exc
            continue
        except httpx.HTTPError as exc:
            last = exc  # transport-level: a reset, a timeout, a DNS hiccup
            continue
        return response.content
    raise last if last else RuntimeError("unreachable")


def main() -> None:
    settings = get_settings()
    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    settings.raw_pdf_dir.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    # One client for every paper: connection reuse, and one place for the timeout.
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for index, paper in enumerate(manifest["papers"]):
            arxiv_id = paper["arxiv_id"]
            out_path = settings.raw_pdf_dir / f"{arxiv_id}.pdf"
            if out_path.exists():
                print(f"skip (cached): {arxiv_id}")
                continue

            # Spacing between *papers* as well as between retries. Skipped before the first
            # request so a fully cached corpus costs nothing.
            if index:
                time.sleep(_REQUEST_SPACING_SECONDS)

            try:
                content = _download(client, arxiv_id)
                # `write_bytes` is inside the try because `OSError` -- a full disk, a read-only
                # mount -- is a per-paper failure like any other, and it used to escape and stop
                # the build after N papers had already downloaded.
                out_path.write_bytes(content)
            except (httpx.HTTPError, httpx.InvalidURL, OSError) as exc:
                # Per paper, and the run still ends non-zero -- the same rule as
                # `scripts/ingest.py`. One withdrawn or mistyped id must not stop the corpus
                # build, but a corpus quietly missing a third of its papers is worse than a
                # build that fails: retrieval still answers, from less material than the eval
                # set assumes, which reads as a relevance problem rather than a missing file.
                print(f"FAILED {arxiv_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
                failed.append(arxiv_id)
                continue

            print(f"downloaded: {arxiv_id} -> {out_path}")

    if failed:
        print(f"{len(failed)} of {len(manifest['papers'])} failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
