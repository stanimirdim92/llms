"""Download every PDF listed in data/manifest.json into data/raw_pdfs/, skipping ones already present."""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings

_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
"""arXiv serves the latest version of a paper at its unversioned id, which is what the
manifest stores.

This used to go through the `arxiv` client -- one API search per paper, purely to resolve
`Result.pdf_url` -- and that dependency is gone. It was already only half in use: `arxiv>=4`
removed `Result.download_pdf`, so the file it named was fetched over plain HTTP regardless.
Verified rather than assumed: a HEAD of this URL returns `200 application/pdf`.

One consequence, unchanged either way but worth stating. The id is unversioned, so a revised
paper yields different bytes under the same id -- and since `scripts/ingest.py` uses the arXiv
id as the `doc_id`, that re-ingest correctly *replaces* the document rather than adding a
second copy. `content_hash` in the registry is what records that the bytes moved.
"""


def main() -> None:
    settings = get_settings()
    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    settings.raw_pdf_dir.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    # One client for every paper: connection reuse, and one place for the timeout. Redirects
    # are followed because arXiv answers the unversioned URL with the versioned one.
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for paper in manifest["papers"]:
            arxiv_id = paper["arxiv_id"]
            out_path = settings.raw_pdf_dir / f"{arxiv_id}.pdf"
            if out_path.exists():
                print(f"skip (cached): {arxiv_id}")
                continue

            try:
                response = client.get(_PDF_URL.format(arxiv_id=arxiv_id))
                response.raise_for_status()
            except httpx.HTTPError as exc:
                # Per paper, and the run still ends non-zero -- the same rule as
                # `scripts/ingest.py`. One withdrawn or mistyped id must not stop the corpus
                # build, but a corpus quietly missing a third of its papers is worse than a
                # build that fails: retrieval still answers, from less material than the eval
                # set assumes, which reads as a relevance problem rather than a missing file.
                print(f"FAILED {arxiv_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
                failed.append(arxiv_id)
                continue

            # Written only after a successful response, so an interrupted download cannot leave
            # a truncated PDF that the `out_path.exists()` check above then treats as cached --
            # which surfaces later, inside Docling, as an unparseable file.
            out_path.write_bytes(response.content)
            print(f"downloaded: {arxiv_id} -> {out_path}")

    if failed:
        print(f"{len(failed)} of {len(manifest['papers'])} failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
