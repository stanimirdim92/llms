"""Download every PDF listed in data/manifest.json into data/raw_pdfs/, skipping ones already present."""

import json
import sys
from pathlib import Path

import arxiv
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    settings.raw_pdf_dir.mkdir(parents=True, exist_ok=True)

    client = arxiv.Client()
    for paper in manifest["papers"]:
        arxiv_id = paper["arxiv_id"]
        out_path = settings.raw_pdf_dir / f"{arxiv_id}.pdf"
        if out_path.exists():
            print(f"skip (cached): {arxiv_id}")
            continue

        result = next(client.results(arxiv.Search(id_list=[arxiv_id])))
        if result.pdf_url is None:
            print(f"no PDF link for {arxiv_id}, skipping")
            continue

        # arxiv>=4.0.0 removed the Result.download_pdf convenience method; download
        # the PDF ourselves from the URL it still exposes via `pdf_url`.
        response = requests.get(result.pdf_url, timeout=30)
        response.raise_for_status()
        out_path.write_bytes(response.content)
        print(f"downloaded: {arxiv_id} -> {out_path}")


if __name__ == "__main__":
    main()
