"""Download every PDF listed in data/manifest.json into data/raw_pdfs/, skipping ones already present."""

import json
import sys
from pathlib import Path

import arxiv

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
        result.download_pdf(dirpath=str(settings.raw_pdf_dir), filename=out_path.name)
        print(f"downloaded: {arxiv_id} -> {out_path}")


if __name__ == "__main__":
    main()
