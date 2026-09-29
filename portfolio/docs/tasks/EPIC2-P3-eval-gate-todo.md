> Rewritten 2026-09-24 for LangSmith datasets and experiments. See the plan's header for what
> changed. Tests named here are run by the user or CI, not by a session (user, 2026-09-24).

## T001: Sync script and local example loader — BUILT (sync not yet run against LangSmith)

**Description:** `qa_dataset.jsonl` stays authoritative in git. `scripts/sync_eval_dataset.py`
upserts it into a LangSmith dataset. `app/eval/examples.py` loads the same file into
`Example`s for offline runs, so CI never needs the hosted copy.

**Acceptance criteria:**
- [ ] The sync is idempotent: a second run with no edits changes nothing. It keys examples on
      the pair's stable id, not on position.
- [ ] The dataset version is tagged with the git sha of the `qa_dataset.jsonl` it came from.
- [ ] Each example carries every field a metric reads: question, accepted answer, intent label,
      `answerable`, golden chunk ids, and question class.
- [ ] A pair deleted locally is removed from the LangSmith dataset rather than left behind.
- [ ] The local loader and the sync read the file through one function, so the hosted and
      offline datasets cannot diverge.

**Files:** `scripts/sync_eval_dataset.py`, `app/eval/examples.py`, `tests/unit/test_eval_examples.py`
**Scope:** S

---

## T002: Recording/replay harness — BUILT 2026-09-29 (tests written, not run; never run against the real pipeline)

**Description:** A `--record` pass hits the live Anthropic/Voyage/Qdrant APIs once and writes `vcrpy`
cassettes to `data/eval/cassettes/`. Every other run replays with `record_mode="none"`, where
a cassette miss raises instead of falling through to a real call.

**Acceptance criteria:**
- [x] `vcrpy` is in the `eval` extra; `uv lock` is run and committed.
- [x] Wraps every provider call an eval run makes: generation (`answer_service`), the intent
      classifier, the judges, Voyage rerank and the query embedding, and Qdrant's REST calls.
      (Reasoned from the source and checked per HTTP library against a local server; not yet against
      the real pipeline.)
- [x] Cassettes are stored one per question id (plus `_setup.yaml`), and `meta.json` carries the record
      date, git sha, answer/router/judge/Voyage model ids and the pipeline settings.
- [x] A network guard proves a replayed run makes zero live calls: a non-loopback socket connect aborts
      the run even when the app swallows the error. (Written, not run.)
- [ ] Recorded runs replay identically on two passes. **Needs the first real recording.**
- [x] A cassette miss aborts naming the pair even when the app swallows it, and so does a recorded
      request that goes unplayed (the reranker's fallback would otherwise degrade silently).
- [x] Auth headers never reach a cassette: allow-listed request and response headers, plus a scan of
      every cassette at record time (which deletes them on a hit) and at replay time.

**Files:** `app/eval/replay.py`, `scripts/run_eval.py`, `pyproject.toml`, `uv.lock`, `data/eval/cassettes/`, `tests/unit/test_eval_replay.py`
**Scope:** M

---

## CP-001: Offline evaluation proven — RESOLVED: `aevaluate` isn't network-free; the gate doesn't use it

- [ ] `aevaluate(target, data=<local examples>, evaluators=[trivial], upload_results=False)`
      completes with `LANGSMITH_API_KEY` unset and the network blocked.
- [ ] If it doesn't, record why and switch the gate (T007) to calling the metric functions
      directly on target outputs, without `aevaluate`.

---

## T003: Eval target over the `/ask` pipeline — BUILT

**Description:** A target function takes one example's inputs and returns a structured output:
`predicted_intent`, `retrieved_chunk_ids` in rank order, `answer`, `citations`, `latency_ms`,
`input_tokens`, `output_tokens`. It calls the same code `/ask` does, not a reimplementation.

**Acceptance criteria:**
- [ ] It goes through `classify_intent` and the same branch logic as `ask()`. A metadata
      question must not reach retrieval here either.
- [ ] Runs against the seeded eval tenant (`corpus_manifest.json`'s pinned `seed_tenant_id`).
- [ ] Retrieved chunk ids come from the reranked list the answer was built from, in order.

**Files:** `app/eval/target.py`, `tests/unit/test_eval_target.py`
**Scope:** M

---

## T004: Retrieval, routing and citation evaluators — BUILT

**Description:** Plain functions in `app/eval/metrics.py`, each wrapped as a LangSmith
evaluator (per example) or summary evaluator (per experiment):
- recall@k and nDCG@k / MRR against the golden chunk ids;
- routing accuracy, per example plus a 4×4 confusion matrix as a summary;
- citation success rate: every citation resolves to a real, in-range chunk.

**Acceptance criteria:**
- [ ] Every metric is also reported per question class, not only in aggregate.
- [x] Pairs with nothing to retrieve are excluded from retrieval metrics rather than scored as misses:
      a pair is scored when it is answerable and has golden chunk ids, **whatever its intent** (changed
      2026-09-29; it required `factual`, which dropped the cross-document pairs once they were
      relabelled `aggregate`).
- [ ] The wrappers are thin; the logic is testable without LangSmith installed or configured.

**Files:** `app/eval/metrics.py`, `tests/unit/test_eval_metrics.py`
**Scope:** M

---

## T005: LLM-as-judge evaluators — BUILT (not yet run)

**Decided 2026-09-24 (user): LangSmith-style judges on Claude, not `ragas`.**

- `correctness`: the answer states what the accepted answer states. For an unanswerable pair,
  that means declining. An `/ask` error scores 0, not skipped.
- `groundedness`: every claim is supported by the retrieved chunk texts (`TargetOutput.retrieved_texts`).
- `factual` and `aggregate` pairs (`JUDGED_INTENTS`, since 2026-09-29); `metadata` and `out_of_scope`
  are registry reads and fixed refusals, covered by routing accuracy.
- Structured output via `json_schema` rather than a forced tool call, so thinking can stay on
  for the default Opus judge.
- Run locally with `run_eval.py --judges`; `--upload` always runs them.
- Judge calls are recorded in the same per-pair cassette as the question, so `--record --judges` /
  `--replay --judges` cover them and CI makes no live calls. Replay must pass `--judges` if and only if
  the recording did (`meta.json` records which).

**Files:** `app/eval/judges.py`, `app/eval/langsmith_evaluators.py::answer_judges`, `app/config.py::eval_judge_model`

---

## T006: Record the baseline

**Configuration decided (user, 2026-09-24):** today's pipeline as it ships, real chunker and
reranker, with nothing switched off.

**How (2026-09-29):** `run_eval.py --record --judges --write-baseline` writes the cassettes and the
baseline in one pass, after fetch → seed → `eval_registry.py export` (the full sequence is in the
script's docstring). Commit `data/eval/cassettes/`, `baseline_scores.json` and `registry_fixture.json`
together. **Then run `--replay --judges --gate` once** before pushing: the gate must reproduce the
baseline exactly, which is the first real check that replay works. Note the cross-document pairs are
now `aggregate`: with `AGGREGATE_ANSWERING` off (the default) they are answered by the "not supported"
refusal, so their retrieval and citation cells record 0 -- record with the flag on if that is
not the baseline wanted, and set the same in the `eval-gate` job's environment (`meta.json` records it,
and a mismatch warns and then misses).

**Description:** A human-run `--record` pass that uploads an experiment to LangSmith, then
writes its summary scores (metric × question class) to `data/eval/baseline_scores.json`.
(`--record` and `--upload` are mutually exclusive, so the experiment id is a separate `--upload` run.)

**Acceptance criteria:**
- [ ] The file's header records the git sha and model ids the baseline was taken with.
- [ ] `baseline_scores.json` is small, sorted and stable, so a PR diff of it is readable.
- [ ] The LangSmith experiment id is recorded in the file for cross-reference.

**Files:** `data/eval/baseline_scores.json`, `data/eval/cassettes/`
**Scope:** S

---

## T007: CI gate job — JOB BUILT 2026-09-29, skips visibly until cassettes exist

**Description:** A new `eval-gate` job builds examples from the local `qa_dataset.jsonl`,
replays cassettes, and evaluates offline (CP-001). It compares against
`baseline_scores.json` with a stated per-metric tolerance.

**Acceptance criteria:**
- [x] Zero live network calls; no CI secrets needed (dummy keys, a never-resolving `QDRANT_URL`,
      tracing off; see T002).
- [x] Fails naming the metric and question class that moved, not an aggregate score
      (`Regression.describe`, unchanged).
- [x] Warns, but doesn't fail, when `meta.json` is older than 90 days (`STALE_AFTER`) or its model ids
      or pipeline settings differ from the current ones.
- [x] Skips with a warning annotation and a job-summary message while `data/eval/cassettes/*.yaml`
      does not exist. A partial recording (cassettes but no `meta.json`) fails instead of skipping.
- [ ] ~~**Acceptance test:** with the reranker removed, the gate fails and the message points at a
      rank-sensitive metric.~~ **Cannot work under strict replay, by design:** removing the reranker
      changes the requests (no Voyage rerank call, a different Anthropic body), and a changed request
      is a cassette *miss* that aborts the run before any metric exists. Replaced by
      `tests/unit/test_eval_gate.py`, which scores the ranking a reranker-less pipeline would produce
      and asserts `compare` fails on `ndcg_at_5` and `mrr` while `recall_at_5` stays green. The
      joined claim (real reranker removed -> that ranking) is unproven until a re-record without it.
- [ ] The job has actually gated once, on a committed recording.

**Files:** `.github/workflows/portfolio-ci.yml`, `app/eval/gate.py`, `tests/unit/test_eval_gate.py`
**Scope:** M
