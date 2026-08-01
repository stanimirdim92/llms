<!--
Keep the sections that apply and delete the rest. A template filled in with "n/a" everywhere
is noise; a short PR with two honest sections is not.
-->

## What changed, and why

<!-- The reason matters more than the diff. The diff is right there. -->

## How it was verified

<!--
Paste the real output, not a claim that you ran it. From `portfolio/`:

    uv run ruff check . && uv run ruff format --check . && uv run ty check
    uv run pytest tests/unit
    docker compose -f .docker/docker-compose.yml config    # after any compose/Dockerfile edit

**Include the skip count.** The auth, rate-limit, and worker/registry suites hit a real
Postgres or Redis and skip when one is unreachable, so a local run can be green having tested
much less than it looks. `N passed, 0 skipped` is the only unqualified pass. CI provides both
services and asserts none of the three skipped.
-->

```
```

## Anything unverified

<!--
State it plainly. "I couldn't check this" must never read as "this works" — an unverified
claim that survives review becomes a documented fact nobody re-checks. Also fine here: a
measurement you could not take, a path you could not exercise locally, a decision you are
unsure about.
-->

---

### Checks that catch this repo's silent failures

<!-- Tick what applies. Skip the whole block for docs-only changes. -->

- [ ] **Tenant boundary.** New route takes `tenant_id: CurrentTenant`; every new query has
      `tenant_id` in the WHERE clause, not in an `if` afterwards. A wrong filter here returns
      another tenant's data rather than raising. (`.claude/skills/add-endpoint`)
- [ ] **Client-supplied ids** are resolved against the caller's own rows before reaching a
      Qdrant filter. `doc_id` embeds a tenant prefix, so it looks authoritative on its own.
- [ ] **Re-ingestion stays correct.** Anything changing how many chunks a document yields
      (chunk size, a Docling upgrade, `do_ocr`) shifts every later chunk id — the delete step
      in `QdrantStore.upsert` is what stops the old points lingering as retrievable staleness.
- [ ] **No ingestion imports in the api.** Routers must not import `app.ingestion.*`; it costs
      ~2s of startup per process and `tests/unit/test_upload_formats.py` pins it.
- [ ] **`uv.lock` regenerated and committed** if `pyproject.toml` changed (`uv lock`).
- [ ] **Docs updated where they became false.** `TECHNICAL_DECISIONS.md` for a changed
      decision, `CLAUDE.md` for a new invariant, `MEMORY.md` for state a future session needs.
      `docs/IMPLEMENTATION_PLAN.md` is history and is deliberately not kept current.

### Related

<!-- Closes #N, or the EPIC_*_PLAN.md phase this implements. -->
