---
name: changelog
description: Write and maintain this project's CHANGELOG.md -- what a person using the API, the CLI or the Docker stack would notice changed. Use this whenever asked to write, update, regenerate or "catch up" a changelog or release notes, whenever a change lands that alters observable behaviour (an endpoint, a response field, an env var, a default, a deleted feature), and before tagging or cutting a release. Also use it when asked what changed recently or what would break on upgrade -- the answer belongs in this file rather than reconstructed from git log each time. Reach for it even when the request is phrased as "summarise the last N commits", because a commit summary and a changelog entry are different artefacts and this skill is about the difference.
---

# Writing this project's changelog

The changelog answers one question: **what would someone who uses this notice, and what
would break if they upgraded?** Everything else — why, how, what we learned, what it cost —
belongs somewhere else, and keeping that line is most of the work.

## First, the boundary that makes this file worth keeping

`CLAUDE.md` defines a document set and says plainly that two files covering one topic
disagree within a month. `CHANGELOG.md` sits closest to `docs/MEMORY.md`'s session log, so
the split has to be sharp:

| | `CHANGELOG.md` | `docs/MEMORY.md` session log |
|---|---|---|
| Audience | someone using the system | the next session working on it |
| Content | what changed, what breaks | why, what was measured, what we got wrong |
| Voice | present tense, user-facing | narrative, first person, internal |
| Test | "would a caller notice?" | "would the next maintainer need it?" |

So `MEMORY.md` records that the sliding-window *counter* granted 2 of 10 requests to a client
that waited the advertised `Retry-After`, with the measurement table. The changelog records
that `Retry-After` is now safe to obey literally. Same commit, different artefact.

**A changelog entry that explains itself is in the wrong file.** If you find yourself writing
"because", stop and check whether that clause belongs in `MEMORY.md` or
`docs/TECHNICAL_DECISIONS.md`. One short parenthetical is fine when the *user* needs the
reason to act; a paragraph is a sign you have drifted.

## Versioning: there are no releases yet

`pyproject.toml` says `0.0.1`, there are no git tags, and nothing has been published. Do not
invent version numbers — a changelog that claims `1.2.0` when no such thing exists is worse
than no changelog, because it looks authoritative.

Until a real release exists, use `## [Unreleased]` at the top and group everything under
dated headings beneath it:

```markdown
## [Unreleased]

### 2026-08-04

#### Removed
- ...
```

When a version is eventually tagged, rename the relevant `[Unreleased]` block to
`## [0.1.0] - 2026-08-04` and open a fresh `[Unreleased]`. Dated sub-headings mean that
rename is a one-line edit rather than a reconstruction.

## Categories

Keep a Changelog's six, in this order, and skip any that are empty:

`Added` · `Changed` · `Deprecated` · `Removed` · `Fixed` · `Security`

Two judgement calls come up constantly here:

- **Changed vs Fixed.** `Fixed` is for behaviour that was *wrong* — a header that lied, a
  filter that returned too much. `Changed` is for behaviour that was fine and is now
  different. When a change is both a fix and a behaviour change, file it under `Fixed` and
  say what the new behaviour is; readers scanning for breakage look there first.
- **Removed is where breakage lives.** A deletion is the most likely thing to break a
  working setup, so every `Removed` entry needs the migration in the same breath — see below.

## Running it

Start from the last entry's date rather than a commit count — "the last 10 commits" is an
arbitrary window that splits a day's work in half.

```bash
git log --format="%ad %h %s" --date=short          # find where the changelog stops
git log --stat --format="" <since>..HEAD           # what actually moved
```

Then, for each commit, decide before writing anything:

1. **Did any user-visible surface change?** `app/api/`, `app/config.py`, the compose file, the
   Dockerfile's runtime behaviour, `scripts/`. Changes confined to `tests/`, `docs/`,
   `.claude/` or a docstring produce no entry.
2. **What would a caller notice?** Write that sentence. If you cannot write it without
   describing internals, there is probably no entry to write.
3. **Would it break a working setup?** If yes, `Removed` or `Fixed` with a **Breaking:** prefix
   and a migration line.

A commit that produces no entry is the common case, and recording nothing for it is correct.
Resist the pull to give every commit a line — a changelog padded with internal churn stops
being read, which costs more than the omissions it prevents.

## Deriving entries from commits

This project's commit messages are unusually long and carry the full reasoning. That is a
gift and a trap: the *body* is mostly `MEMORY.md` material, and the *subject* is written for
a reviewer rather than a user. Translate; never paste.

Read the diff, not just the message, when the message is about internals.

**Example 1 — a subject that means nothing to a user:**
Commit: `Fix the L-tail: L2-L8, L10, L12-L14, L16-L22`
Entry: nothing under that name. Open the diff, find the handful of items that changed
observable behaviour, and write those individually. Review-finding identifiers are internal
bookkeeping.

**Example 2 — reasoning belongs elsewhere:**
Commit: `Switch to MovingWindowRateLimiter: the counter ignored its own Retry-After`
Entry: `- **`Retry-After` is now safe to obey literally.** Waiting the advertised time returns your full budget.`
The 10-of-10-versus-2-of-10 measurement is `MEMORY.md`'s.

**Example 3 — a removal needs a migration:**
Commit: `Remove the shared corpus and the `global` tenant`
Entry, under `Removed`, with the upgrade note attached rather than in a separate section, so
nobody reads half of it.

**Example 4 — no entry:**
Commit: `Randomise test order instead of running the suite three times`
Entry: none. It changes how contributors run tests, not what the system does. If the project
later grows a contributor-facing changelog, it belongs there.

## Breaking changes

Mark them inline with a bold **Breaking:** prefix and attach the action the reader has to
take. A breaking change without a migration line is a bug report waiting to happen:

```markdown
#### Removed
- **Breaking: the shared `global` corpus is gone.** Every document now belongs to the tenant
  that uploaded it, so a fresh install has nothing to search until something is uploaded.
  *Upgrading:* points tagged `global` are orphaned — they match no live tenant filter and no
  longer appear in the registry, so drop the Qdrant volume and re-upload.
```

Do not add a separate "Breaking changes" section at the top. It duplicates, and duplicates
drift.

## Style

- **Present tense, describing the new state.** "`Retry-After` is safe to obey" beats "fixed
  `Retry-After` so that it is now safe to obey."
- **Lead with the noun the reader knows** — the endpoint, the env var, the header, the flag.
  Bold it. Someone scanning for `X-RateLimit-Reset` should find it without reading prose.
- **Name the thing exactly as they'd type it.** `POST /v1/documents`, not "the upload
  endpoint". `STREAMLIT_BROWSER_SERVER_ADDRESS`, not "the Streamlit address setting".
- **No commit hashes, no PR numbers, no internal identifiers** (`H1`, `M14`, `L-tail`). They
  are unresolvable for a reader and the git history already has them.
- **No credit lines or authorship.** This is a record of the software, not of the work.
- **One line per change where possible.** Two if a migration is needed.

## Verify before you claim

The same rule that governs every other document here: write nothing you have not checked.

- Read the code or the diff for each entry. A changelog assembled from commit subjects
  inherits every stale claim in them, and this project has caught several.
- Confirm names against the source: env vars against `app/config.py`, routes against
  `app/api/routers/`, response fields against `app/api/schemas.py`.
- If a change's user-visible effect is genuinely unclear, say so in the entry rather than
  guessing a confident description. "Behaviour under X is unverified" is a legitimate line
  and is much cheaper than a reader trusting a wrong one.

## Keeping it current

Update it in the same commit as the change, not in a sweep afterwards. A sweep means
reconstructing intent from diffs, which is where invented entries come from.

If you add or restructure this file, update the document-set table in `CLAUDE.md` and the one
in `docs/MEMORY.md` so the set stays a set. Six documents that describe themselves is the
reason the split holds; a seventh that nothing points at is how it stops holding.

## Deliberately not doing

Two conventions from the general-purpose changelog skills in the wild
(e.g. `ComposioHQ/awesome-claude-skills`'s `changelog-generator`), and why they are declined
here rather than overlooked:

- **Emoji category markers** (✨ features, 🐛 fixes). Every other document in this project is
  plain dense prose; emoji headings would read as a different voice pasted in. The Keep a
  Changelog category names already do the scanning work.
- **A separate `CHANGELOG_STYLE.md`.** Style lives in this skill. One project, one style, and a
  second file describing how to write the first is exactly the two-files-one-topic split that
  `CLAUDE.md` warns drifts within a month.

What *is* worth taking from those skills is the framing: a changelog is a translation job, and
the noise filter is a feature. Both are above.
