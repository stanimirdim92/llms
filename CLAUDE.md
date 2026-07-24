# Repo

Four independent projects, no shared code: `portfolio/` is the active one (an AI
engineer portfolio -- RAG, LLM eval, agentic HITL); `fastai-dl/`,
`transformers-course/`, and `LLM Engineers Handbook/` are course and book
material. Each carries its own tooling -- don't assume a command that works in
one works in another. `portfolio/CLAUDE.md` has that project's own rules and
failure contracts.

# Coding rules

Rules 1-4 are Andrej Karpathy's, from his January 2026 post on recurring LLM
coding failure modes. Rules 5-7 are three of the community extensions credited
to @mnilax, kept deliberately -- the rest of that set was dropped as either
redundant with how this project already works or built on arbitrary thresholds.
Numbering here is therefore our own past rule 4; don't expect it to line up with
a published twelve-rule list. Each rule names the failure it exists to catch,
which is the part that makes it actionable instead of generic.

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
