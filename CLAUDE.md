# Repo

Four independent projects, no shared code: `portfolio/` is the active one (an AI
engineer portfolio -- RAG, LLM eval, agentic HITL); `fastai-dl/`,
`transformers-course/`, and `LLM Engineers Handbook/` are course and book
material. Each carries its own tooling -- don't assume a command that works in
one works in another. `portfolio/CLAUDE.md` has that project's own rules and
failure contracts.

**This file is general.** Everything here applies to any project in the repo and
would transfer to a new one. Anything true of only one project belongs in that
project's own `CLAUDE.md`, and anything that is *current state* rather than a
rule belongs in its `docs/MEMORY.md`. Mixing the three buries the rules in
changelog.

# Coding rules

Rules 1-4 are Andrej Karpathy's, from his January 2026 post on recurring LLM
coding failure modes. Rules 5-7 are three of the community extensions credited
to @mnilax, kept deliberately -- the rest of that set was dropped as either
redundant with how this project already works or built on arbitrary thresholds.
Numbering here is therefore our own past rule 4; don't expect it to line up with
a published twelve-rule list. Each rule names the failure it exists to catch,
which is the part that makes it actionable instead of generic.

Rules 8-15 are ours, and every one was written after the failure it describes
actually happened here. That is the bar for adding another: not "this is good
practice" but "this cost us something, and here is what it was."

## Karpathy's four

1. **Think before coding.** Plan before editing. Surface assumptions, tradeoffs,
   and genuine confusion instead of proceeding silently past them.
   *Catches: confidently building the wrong thing.*

2. **Simplicity first.** Smallest change that works. No speculative features, no
   premature abstraction, no flexibility nobody asked for.
   *Catches: a 200-line solution to a 20-line problem.*

3. **Surgical changes.** Touch only what the task names. Don't refactor working
   code just because you happened to read it.
   *Catches: unrelated diffs that make review impossible.*

4. **Goal-driven execution.** Define "done" up front as something verifiable,
   then loop until it's confirmed -- not until it looks right.
   *Catches: declaring success without running anything.*

## Kept extensions

5. **Use the model only for judgment calls.** Reserve LLM calls for
   classification, extraction, and drafting. Deterministic operations get plain
   code.
   *Catches: paying latency and nondeterminism for work `if`/`else` would do.*

6. **Surface conflicts, don't average them.** When two patterns in the codebase
   contradict each other, pick one and say why. Never blend them into a third
   thing that matches neither.
   *Catches: inventing a novel pattern nobody chose.*

7. **Fail loud.** Surface uncertainty, skipped steps, and unverified claims
   explicitly. Never let "I couldn't check this" read as "this works".
   *Catches: silent gaps the reader assumes were covered.*

## Ours, each from an actual incident

8. **Absent data must mean the pre-existing behaviour.** A new nullable column,
   flag, or list has to read as "carry on as before" for every row written
   before it existed -- `NULL` expiry means *never expires*, an empty permission
   list means *every* permission. Then check the inverse: a default that means
   "unrestricted" makes *omitting* the field a privilege escalation, so the
   guard has to run on the materialised value, not the submitted one.
   *Catches: shipping a column that silently disables every existing record.*

9. **Fail fast on configuration, fail open on guardrails.** Decide per component
   by asking what an outage of *this* thing means. Missing credentials should
   abort at boot -- a process that starts and then fails every request passes
   the liveness probe. A rate limiter whose store is unreachable should allow
   the request and log loudly, because a guardrail's outage must not become the
   service's outage.
   *Catches: silent-startup-into-total-failure, and an optional dependency
   taking the service down with it.*

10. **Put the authorization predicate in the query, never in an `if` after it.**
    Filtering after the read means the row was already read, and the shape that
    looks correct -- a lookup by a global id, checked afterwards -- returns
    someone else's data when ids collide across owners.
    *Catches: cross-tenant reads, which return data instead of raising and so
    stay invisible until a user reports seeing a stranger's record.*

11. **Refuse rather than answer from the wrong material.** An unowned identifier
    is a 404, not a silent fallback to searching everything. An empty parse is
    an error, not a stored row with `count=0`. A model's "I can't see the image"
    is not a caption.
    *Catches: a fluent, confident, wrong answer -- indistinguishable from a
    correct one at the point of use.*

12. **A skipped test is not a passing test.** Read the skip count, every time.
    Suites that need a real service skip when it is unreachable, so a green
    local run can have tested almost nothing. CI must assert the count.
    *Catches: the most expensive false confidence, because it is
    self-reinforcing -- every later green run inherits it.*

13. **Verify a claim about a dependency by resolving or running it.** Not from
    memory, not from the README, and not from what was true last year. Pin the
    versions when you probe: a resolver asked for a package *unpinned* will
    happily satisfy it with a release from 2018 rather than reporting the
    conflict, so the unpinned probe answers a different question than the one
    you asked.
    *Catches: a plausible constraint repeated into a decision record, where it
    then gets believed for months.*

14. **Measure before making a performance claim, and warm up first.** The first
    run of a concurrent benchmark measures connection-pool construction, not the
    thing under test -- one pass showed the async path five times *slower* until
    the pool was warmed and the run repeated.
    *Catches: publishing a benchmark artefact as a finding, then designing
    around it.*

15. **Comments record the failure, not the mechanism.** Write what breaks if
    this line changes, not what the line does. Then mutation-test the guard:
    remove the code and confirm a test goes red. A test that passes with the
    feature deleted is documentation, not verification.
    *Catches: a later reader -- human or model -- deleting a subtle constraint
    because the code looked redundant, with the suite still green.*

# The document set

`portfolio/` keeps these six, and a new project should start the same way; the
course directories have a README and nothing else, which is correct for what
they are. The split is what keeps any of them worth reading -- two files
covering one topic disagree within a month.

| File | Holds | Changes when |
|---|---|---|
| `README.md` | The system as it is, for someone who has never seen it. | Behaviour a user can observe changes. |
| `CLAUDE.md` | Rules and failure contracts. Imperative, timeless. | A new way to break the system is found. |
| `docs/PATTERNS.md` | Recurring shapes, each with the failure it prevents — plus what is deliberately *absent*, so a reviewer doesn't "fix" it. | The architecture changes. |
| `docs/TECHNICAL_DECISIONS.md` | Why each technology, and what was rejected and why. | A decision is revisited — update this, not the plan. |
| `docs/IDEAS.md` | The parking lot, plus a *considered and rejected* table. | Any time something occurs to you. |
| `docs/MEMORY.md` | Where the work actually is: standing directives, open questions, measurements, session log. | Every working session. |

Three habits that make the set work:

- **Read `MEMORY.md` first in a new session and update it last.** Nothing else
  carries state across sessions.
- **Record a measurement the first time you take it.** A number measured once
  and written down beats the same number re-derived approximately three times.
- **Write nothing you have not verified.** An unverified claim recorded here is
  read as established fact by the next session -- which is rule 7 with a longer
  blast radius.

# Working agreements

- **Never commit a real secret.** `.env` stays untracked; `.env.example` holds
  placeholders only. Treat every repo as public: a key that reaches a commit is
  disclosed the moment it is pushed, whether or not the commit is reverted.
- **Commit the lockfile, and install from it everywhere** -- CI and images
  included. Without it the build re-resolves and CI can test a dependency set
  nobody deployed.
- **Run the project's full gate before pushing**, from its own `CLAUDE.md` or
  its `verify` skill rather than from memory. Report what actually ran,
  including anything that was skipped.
- **Randomise test order; don't run the suite three times.** This replaced a rule to run it
  three times, which sounded stronger than it was: pytest orders tests identically on every
  run, so three identical passes can only catch timing races and state leaking *between*
  runs -- never a test that passes solely because another ran first, which is the flake the
  rule was reaching for. `pytest-randomly` reorders every run and reseeds `random` per test.
  One randomised pass beats three ordered ones, and the seed is printed (`-v`, or
  `--randomly-seed=last` to replay) so a red run stays reproducible. Shared-database
  fixtures and counters that outlive a test are what bit here, and order is how they bite.
