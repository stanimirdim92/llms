"""The golden set, read from the one place it is authoritative: `data/eval/qa_dataset.jsonl`.

The LangSmith dataset is a synced copy (`scripts/sync_eval_dataset.py`) and the offline gate
reads the file directly. Both go through `load_golden`, so the hosted and local datasets cannot
disagree about what a pair contains.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.config import DATA_DIR

if TYPE_CHECKING:
    from pathlib import Path

EVAL_DIR = DATA_DIR / "eval"
QA_DATASET_PATH = EVAL_DIR / "qa_dataset.jsonl"
CORPUS_MANIFEST_PATH = EVAL_DIR / "corpus_manifest.json"

_EXAMPLE_ID_NAMESPACE = uuid.UUID("6f1c2d0e-7a51-4c3b-9e8f-2b4d5a6c7e81")
"""Fixed forever. LangSmith example ids are derived from it and the pair id, so re-syncing
updates the same examples instead of creating duplicates. Changing it orphans every example."""


@dataclass(frozen=True)
class GoldenPair:
    id: str
    question: str
    intent: str
    kind: str
    answerable: bool
    answer: str
    chunk_ids: tuple[str, ...]

    @property
    def scores_retrieval(self) -> bool:
        """Retrieval metrics apply only where there is a right chunk to find.

        An unanswerable or non-factual pair has no golden chunks, and scoring it as a miss would
        punish the system for correctly finding nothing.
        """
        return self.intent == "factual" and self.answerable and bool(self.chunk_ids)

    @property
    def example_id(self) -> uuid.UUID:
        return uuid.uuid5(_EXAMPLE_ID_NAMESPACE, self.id)


def load_golden(path: Path = QA_DATASET_PATH) -> list[GoldenPair]:
    pairs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        pairs.append(
            GoldenPair(
                id=row["id"],
                question=row["question"],
                intent=row["intent"],
                kind=row["kind"],
                answerable=row["answerable"],
                answer=row["answer"],
                chunk_ids=tuple(row["chunk_ids"]),
            )
        )
    if not pairs:
        # An empty golden set would make every metric vacuous and the gate green.
        msg = f"no golden pairs in {path}"
        raise ValueError(msg)
    return pairs


def seed_tenant_id(path: Path = CORPUS_MANIFEST_PATH) -> str:
    """The pinned tenant the corpus was seeded under. Every golden chunk id is a function of it."""
    return json.loads(path.read_text(encoding="utf-8"))["seed_tenant_id"]
