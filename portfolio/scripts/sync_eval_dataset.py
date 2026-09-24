"""Copy the golden set into its LangSmith dataset. `qa_dataset.jsonl` stays the authority.

    uv run python scripts/sync_eval_dataset.py            # create or update, then tag with the git sha
    uv run python scripts/sync_eval_dataset.py --dry-run  # show what would change, touch nothing

Needs `LANGSMITH_API_KEY`. Idempotent: example ids are derived from each pair's id, so a second
run with no edits changes nothing, and a pair deleted locally is deleted remotely rather than
left behind to be scored against forever.
"""

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.eval.golden import load_golden
from app.eval.langsmith_evaluators import DATASET_NAME, example_payload


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the changes without making them")
    parser.add_argument("--dataset", default=DATASET_NAME, help=f"LangSmith dataset name (default {DATASET_NAME})")
    args = parser.parse_args()

    # Settings bridges `.env`'s LANGSMITH_* into the env vars the LangSmith SDK reads.
    if not get_settings().langsmith_api_key.get_secret_value().strip():
        print("LANGSMITH_API_KEY is not set -- nothing to sync to.", file=sys.stderr)
        return 1
    from langsmith import Client  # noqa: PLC0415 -- only this script talks to the hosted dataset

    client = Client(api_key=get_settings().langsmith_api_key.get_secret_value())
    wanted = {str(p["id"]): p for p in (example_payload(pair) for pair in load_golden())}

    if client.has_dataset(dataset_name=args.dataset):
        dataset = client.read_dataset(dataset_name=args.dataset)
    elif args.dry_run:
        print(f"would create dataset {args.dataset} with {len(wanted)} examples")
        return 0
    else:
        dataset = client.create_dataset(args.dataset, description="Golden set, synced from data/eval/qa_dataset.jsonl")

    existing = {str(example.id): example for example in client.list_examples(dataset_id=dataset.id)}
    to_create = [p for key, p in wanted.items() if key not in existing]
    to_update = [
        p
        for key, p in wanted.items()
        if key in existing
        and (existing[key].inputs, existing[key].outputs, existing[key].metadata or {})
        != (p["inputs"], p["outputs"], p["metadata"])
    ]
    to_delete = [key for key in existing if key not in wanted]

    print(f"{len(to_create)} to create, {len(to_update)} to update, {len(to_delete)} to delete")
    if args.dry_run:
        return 0

    if to_create:
        client.create_examples(dataset_id=dataset.id, examples=to_create)
    for p in to_update:
        client.update_example(p["id"], inputs=p["inputs"], outputs=p["outputs"], metadata=p["metadata"])
    for key in to_delete:
        client.delete_example(key)

    sha = _git_sha()
    client.update_dataset_tag(dataset_id=dataset.id, as_of=datetime.datetime.now(datetime.UTC), tag=sha)
    print(f"synced {len(wanted)} examples to {args.dataset}, tagged {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
