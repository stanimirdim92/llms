## T001: Define the run-row schema

**Requirements:** REQ-001 (`docs/EPIC_2_PLAN.md` §2.2 ¶1)

**Description:** One typed row shape naming all 16 columns an eval run emits (this line said
15 until 2026-09-24; the list has always had 16 names):
`run_id, git_sha, question_id, intent_label, predicted_label, chunk_id, doc_id, rank,
vector_score, rerank_score, in_golden_set, judge_verdict, latency_ms, input_tokens,
output_tokens, cost_usd`.

**`cost_usd` — resolved 2026-09-24** (`docs/MEMORY.md` § Open questions #5):

- **Where the prices live:** a committed table in `app/eval/pricing.py`, keyed by the *exact*
  model id `Settings` resolves (`claude-sonnet-5`, `claude-haiku-4-5-20251001`), carrying the date
  it was checked and the source URL. **Not `Settings`:** a price is a fact about the vendor, not
  about a deployment, and an env override would let two runs at the same `git_sha` compute
  different costs for identical token counts -- the row stops being comparable across runs, which
  is the one thing a run store is for.
- **An unpriced model raises**, never prices at 0. A run on a model the table doesn't know would
  otherwise read as free, and a cost regression would hide behind it (root `CLAUDE.md` rule 11).
- **Prices, checked 2026-09-24 against the Anthropic and Voyage pricing pages** (USD per MTok):
  Sonnet 5 $2 in / $10 out (the $2/$10 "intro" rate is now standard -- the scheduled rise to
  $3/$15 on 2026-09-01 was cancelled); Haiku 4.5 $1 / $5. Cache and batch rates are not needed:
  nothing here caches (see the prompt-caching measurement in `docs/MEMORY.md`) or batches.
- **What it covers, stated so a sum isn't over-read:** only calls whose usage is actually
  recorded. Today that is the answer call alone (`answer_service` logs `input_tokens` /
  `output_tokens`); the Haiku router call records no usage, and Voyage embed/rerank is billed $0
  under the 200M-token free tier and records no token counts either. Capturing the router's usage
  is a small addition, and until it lands the column under-counts by roughly the router's share.
- **Per question, repeated per row.** A row is (question x retrieved chunk), so `cost_usd` and the
  token columns repeat across a question's rows. Aggregate over distinct `question_id`, or a run's
  cost reads k times too high. The schema test should pin this with a two-chunk example.

**Acceptance criteria:**
- [ ] `app/eval/schema.py` defines the row type with exactly these 16 fields, typed
      (verify against whichever typing convention `app/registry`'s models already use —
      SQLModel is the project's ORM pattern elsewhere, but this is not a DB table, so a
      plain dataclass/TypedDict is more likely appropriate; confirm during implementation
      rather than assuming SQLModel applies here)
- [ ] A unit test asserts the column set and each column's dtype explicitly (not just
      "the object has these attributes") — this is the guard a later accidental
      column rename or type change should break

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_eval_schema.py -v`
- [ ] Build/static check succeeds: `uv run ty check .`

**Dependencies:** None

**Workstream:** ws-2.2

**Context pointers:**
- Project/module rules: None
- Closest precedent: None (first schema of this kind in the repo)
- Shared contract/invariant: This schema is the contract Phase 2.3 (recall@k, routing
  accuracy, RAGAS wrapping, the CI gate) and Phase 2.4/2.5's gated-shipping checks all
  read from — do not rename a column without checking those plans.

- [ ] `app/eval/pricing.py` holds the price table above and a `cost_usd(model, input_tokens,
      output_tokens)` that raises on an unknown model; a test asserts the raise, and one asserts
      the 2026-08-01 measured answer (3,447 in + 1,013 out on Sonnet 5) prices at **$0.017024**

**Files/areas touched:**
- `app/eval/schema.py`
- `app/eval/pricing.py`
- `tests/unit/test_eval_schema.py`

**Estimated scope:** S

---

## T002: Parquet writer + DuckDB query helper

**Requirements:** REQ-002, REQ-003 (`docs/EPIC_2_PLAN.md` §2.2 ¶2); TD-001, TD-002

**Description:** `app/eval/run_store.py` — `write_run(rows, run_id) -> Path` writing
`data/eval/runs/<run_id>.parquet`, and a DuckDB query helper reading
`data/eval/runs/*.parquet`. `duckdb` and `pyarrow` imported lazily inside functions only.

**Acceptance criteria:**
- [ ] `write_run()` writes exactly one parquet file at `data/eval/runs/<run_id>.parquet`
      per call, using T001's schema
- [ ] A query helper runs arbitrary SQL against `data/eval/runs/*.parquet` via
      `duckdb.sql(...)` (or equivalent) and returns a typed/tabular result
- [ ] No `import duckdb` / `import pyarrow` at module top level anywhere in `app/eval/` —
      both imported inside the functions that use them, `# noqa: PLC0415`, matching
      `app/retrieval/reranker.py:20-22`
- [ ] `duckdb` added to a new `[project.optional-dependencies].eval` group in
      `pyproject.toml`; `uv lock` run and the updated `uv.lock` committed in the same
      change (`pyarrow`/`pandas` need no new declaration — already present as Streamlit
      transitives, confirmed by recon)
- [ ] A unit test asserts `app.api.main`'s import graph does not reach `app.eval.*`
      (mirrors the existing api/ingestion-stack boundary test pattern named in
      `portfolio/CLAUDE.md` § Producer/consumer split — same shape, new module)

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_eval_run_store.py -v` (round-trip a
      handful of rows through `tmp_path`, no live services needed)
- [ ] Build/static check succeeds: `uv run ruff check . && uv run ty check .`

**Dependencies:** T001

**Workstream:** ws-2.2

**Context pointers:**
- Project/module rules: `portfolio/CLAUDE.md` § "The api must not import the ingestion
  stack" — same failure shape applies here for the `eval` extra
- Closest precedent: `app/retrieval/reranker.py:16-25`
- Shared contract/invariant: T001's row schema

**Files/areas touched:**
- `app/eval/run_store.py`
- `pyproject.toml`, `uv.lock`
- `tests/unit/test_eval_run_store.py`

**Estimated scope:** M

---

## T003: Gitignore per-run output

**Requirements:** REQ-002 (`docs/EPIC_2_PLAN.md` §2.2 ¶2); TD-003

**Description:** Prevent `data/eval/runs/*.parquet` from being committed by accident,
while keeping `data/eval/qa_dataset.jsonl` and `data/eval/baseline.parquet` (Phase 2.3)
explicitly committed by name.

**Acceptance criteria:**
- [ ] `.gitignore` gains a `data/eval/runs/` entry, alongside the existing
      `data/eval/results/` line
- [ ] `git status` after a local `write_run()` call shows no new untracked file under
      `data/eval/runs/`
- [ ] `data/eval/qa_dataset.jsonl` and `data/eval/baseline.parquet` remain trackable
      (no broader pattern accidentally shadows them)

**Verification:**
- [ ] Manual check: run T002's writer once locally, confirm `git status` is clean

**Dependencies:** T002

**Workstream:** ws-2.2

**Context pointers:**
- Project/module rules: None
- Closest precedent: `.gitignore:9-14`
- Shared contract/invariant: None

**Files/areas touched:**
- `.gitignore`

**Estimated scope:** XS
