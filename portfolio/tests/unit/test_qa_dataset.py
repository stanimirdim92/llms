"""`data/eval/qa_dataset.jsonl` -- the golden set, checked against the chunk manifest it names.

**The check that matters is the first one.** A chunk id in a golden pair is 65 characters of
derived string (`{tenant}-{digest}-text-0007`); nothing resolves it at authoring time, and a
reference to a chunk that does not exist does not error anywhere downstream -- it simply never
appears in any retrieval, so the pair scores as a permanent miss and the aggregate reads as a
retrieval regression. The same shape as the drift check in `build_eval_chunks.py --check`, from
the other side: that one catches the corpus moving under the dataset, this one catches the
dataset naming something the corpus never had.

**What this file cannot check, stated so a green run is not read as more than it is.** It
proves every golden chunk id *resolves* and still holds the text it was written against. It
cannot prove the id is the *right* one: a pair citing `-text-0009` where `-text-0003` holds the
answer passes everything here, and shows up only as one stubbornly low recall score in the first
eval run. Grounding was checked at authoring time against the full chunk text -- every number in
every answer was found in the chunks it cites -- and that check is not committable, because
`data/eval/chunk_text/` is derived from the papers and therefore not in the repository.

The routing checks are the third part. `metadata`, `out_of_scope` and `aggregate` questions are
answered *without* retrieval on purpose (`CLAUDE.md` § Intent routing), so a golden pair of one of
those intents carrying golden chunk ids would assert the exact defect Phase 2.0 exists to fix.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.generation.intent_router import Intent

_EVAL_DIR = Path(__file__).resolve().parents[2] / "data" / "eval"
_DATASET = _EVAL_DIR / "qa_dataset.jsonl"
_CHUNK_MANIFEST = _EVAL_DIR / "chunk_manifest.json"

_MINIMUM_PAIRS = 50
"""`docs/EPIC_2_PLAN.md` Phase 2.1 asks for 50+. A floor, not a target -- the assertion exists so
that deleting pairs to make a metric move is a failing test rather than a quiet edit.
"""


def _pairs() -> list[dict]:
    return [json.loads(line) for line in _DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]


def _manifest() -> dict:
    return json.loads(_CHUNK_MANIFEST.read_text(encoding="utf-8"))


def _chunk_digests() -> dict[str, str]:
    return {chunk["chunk_id"]: chunk["text_sha256"] for doc in _manifest()["documents"] for chunk in doc["chunks"]}


def _known_chunk_ids() -> set[str]:
    return set(_chunk_digests())


def test_every_golden_chunk_id_exists_in_the_corpus() -> None:
    """The one that cannot be caught later. An id naming nothing is indistinguishable, in every
    metric downstream, from retrieval failing to find a chunk that is really there.
    """
    known = _known_chunk_ids()
    dangling = sorted({chunk_id for pair in _pairs() for chunk_id in pair["chunk_ids"] if chunk_id not in known})

    assert dangling == [], f"golden chunk ids not present in chunk_manifest.json: {dangling}"


def test_every_golden_chunk_still_holds_the_text_it_was_written_against() -> None:
    """The gap `build_eval_chunks.py --check` cannot close, because it compares a rebuild against
    the manifest and would be satisfied by both moving together.

    Regenerate the manifest after a Docling bump and commit it, and every id here still resolves
    -- to a different passage. The digests are copied out of the manifest at authoring time, so
    the pair carries its own evidence of what it was written against, and a corpus that moved
    under the dataset fails here in a second rather than after a 20-minute reparse.
    """
    digests = _chunk_digests()
    moved = sorted(
        f"{pair['id']}:{chunk_id}"
        for pair in _pairs()
        for chunk_id, recorded in zip(pair["chunk_ids"], pair["chunk_text_sha256"], strict=True)
        if digests.get(chunk_id) != recorded
    )

    assert moved == [], (
        f"golden pairs cite chunks whose text has changed since the pair was written: {moved}. "
        f"Re-read those passages before re-recording the digest -- the question may no longer be "
        f"answerable from them."
    )


def test_the_intent_labels_are_the_ones_the_router_can_emit() -> None:
    """Read off `Intent` rather than restated here, so a label added to the router without a
    golden pair -- or a typo in the dataset -- fails rather than silently scoring as a miss in a
    confusion matrix.
    """
    allowed = set(Intent.__args__)
    used = {pair["intent"] for pair in _pairs()}

    assert used <= allowed, f"unknown intent labels: {sorted(used - allowed)}"
    assert used == allowed, f"no golden pairs for: {sorted(allowed - used)}"


def test_only_factual_pairs_carry_golden_chunks() -> None:
    """A `metadata` question is answered from the registry with no Qdrant call at all, and
    `out_of_scope`/`aggregate` refuse. Golden chunk ids on any of those would encode the
    production defect -- a collection-level question answered from whatever chunk happened to be
    nearest in embedding space -- as the expected behaviour.
    """
    misrouted = [pair["id"] for pair in _pairs() if pair["intent"] != "factual" and pair["chunk_ids"]]

    assert misrouted == [], f"non-factual pairs with golden chunks: {misrouted}"


def test_answerability_and_golden_chunks_agree() -> None:
    """`answerable` is what says whether a refusal is the correct response, and the chunk list is
    what recall@k is scored against. If they disagree, one of the two is a lie about the pair.
    """
    wrong = [pair["id"] for pair in _pairs() if bool(pair["answerable"]) is not bool(pair["chunk_ids"])]

    assert wrong == [], f"answerable does not match whether golden chunks were given: {wrong}"


def test_ids_are_unique_and_questions_are_not_repeated() -> None:
    pairs = _pairs()
    ids = Counter(pair["id"] for pair in pairs)
    questions = Counter(pair["question"].strip().lower() for pair in pairs)

    assert [i for i, n in ids.items() if n > 1] == []
    assert [q for q, n in questions.items() if n > 1] == []


def test_the_set_is_at_least_the_size_the_plan_asks_for() -> None:
    assert len(_pairs()) >= _MINIMUM_PAIRS


def test_every_corpus_document_is_asked_about() -> None:
    """A document nothing asks about contributes only distractor chunks: it can lower precision
    and can never be measured. If a paper is genuinely not worth a question it should leave the
    corpus, which changes `corpus_manifest.json` rather than being tolerated here.
    """
    asked = {chunk_id.rsplit("-", 2)[0] for pair in _pairs() for chunk_id in pair["chunk_ids"]}
    unasked = sorted(doc["arxiv_id"] for doc in _manifest()["documents"] if doc["doc_id"] not in asked)

    assert unasked == [], f"corpus documents with no golden question: {unasked}"


@pytest.mark.parametrize("kind", ["table", "cross-document", "unanswerable"])
def test_the_hard_classes_the_plan_names_are_present(kind: str) -> None:
    """Phase 2.1 asks specifically for table lookups, answers spanning two documents, and
    questions the corpus cannot answer. They are the classes a set generated from the corpus does
    not produce, which is why they are named rather than left to a count.
    """
    assert [pair["id"] for pair in _pairs() if pair["kind"] == kind] != []
