# Coding rules

Rules 1-4 are Andrej Karpathy's, from his January 2026 post on recurring LLM
coding failure modes. Rules 5-12 are community extensions (credited to @mnilax);
published variants disagree on which eight they are, so treat these as this
repo's chosen set rather than a canonical list. Each rule names the failure it
exists to catch -- that's the part that makes it actionable instead of generic.

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

## Extensions

5. **Use the model only for judgment calls.** Reserve LLM calls for
   classification, extraction, and drafting. Deterministic operations get plain
   code.
   *Catches: paying latency and nondeterminism for work `if`/`else` would do.*

6. **Respect the token budget.** When a task is ballooning, summarize and restart
   rather than dragging a bloated context forward. (The source proposes hard
   caps -- ~4k per task, ~30k per session; adjust to the task, but treat "this is
   getting long" as a signal to checkpoint, not to push on.)
   *Catches: quality degrading silently as context fills.*

7. **Surface conflicts, don't average them.** When two patterns in the codebase
   contradict each other, pick one and say why. Never blend them into a third
   thing that matches neither.
   *Catches: inventing a novel pattern nobody chose.*

8. **Read before you write.** Understand the file's existing structure and
   conventions before adding to it.
   *Catches: reimplementing a helper that already exists two functions up.*

9. **Tests verify intent, not just behavior.** A test should encode *why* the
   behavior matters, so breaking it tells you what assumption you violated.
   *Catches: tests that pass while the feature is wrong.*

10. **Checkpoint after every significant step.** State what's done, how it was
    verified, and what remains.
    *Catches: long silent runs that end somewhere unintended.*

11. **Match the codebase's conventions.** Conform to what's here, even when you'd
    prefer a different approach. Argue for a change separately from making it.
    *Catches: a file that reads like it came from a different project.*

12. **Fail loud.** Surface uncertainty, skipped steps, and unverified claims
    explicitly. Never let "I couldn't check this" read as "this works".
    *Catches: silent gaps the reader assumes were covered.*
