#!/usr/bin/env python3
"""PreToolUse hook for the read-only subagents: allow Bash only for commands that read.

Without it "read-only" is an instruction, not a boundary. `test-gaps` had Bash and a rule not to
run pytest; an agent that ran it anyway would report a pass, which is a claim rather than a run
(root CLAUDE.md rule 12, one level removed). An allowlist rather than a denylist, because the
dangerous set -- anything that writes, runs the suite, or reaches a service -- is open-ended.

Exit 2 blocks the call and feeds stderr back to the agent. Any other failure (a crash, a missing
interpreter) is non-blocking in Claude Code, i.e. fails OPEN -- so keep this dependency-free.
"""

import json
import re
import shlex
import sys

READ_COMMANDS = {
    "cat",
    "head",
    "tail",
    "wc",
    "ls",
    "grep",
    "rg",
    "find",
    "sort",
    "uniq",
    "cut",
    "tr",
    "awk",
    "sed",
    "diff",
    "jq",
    "tree",
    "file",
    "stat",
    "basename",
    "dirname",
    "realpath",
    "echo",
    "printf",
    "true",
    "pwd",
    "cd",
}
GIT_READ = {
    "diff",
    "log",
    "show",
    "status",
    "blame",
    "ls-files",
    "grep",
    "rev-parse",
    "merge-base",
    "cat-file",
    "ls-tree",
    "shortlog",
    "describe",
}
# Scratch clones are how candidate-triage reads a third-party repo without copying it in.
SCRATCH = ("/tmp/",)


def git_error(args: list[str]) -> str | None:
    # `git -C <dir> diff` is still a read.
    while args[:1] == ["-C"] and len(args) > 1:
        args = args[2:]
    sub = args[0] if args else ""
    if sub in GIT_READ or (sub == "clone" and args[-1].startswith(SCRATCH)):
        return None
    return f"git {sub} is not a read-only git command"


def segment_error(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    cmd, args = tokens[0], tokens[1:]
    if cmd == "git":
        return git_error(args)
    error = None
    if cmd not in READ_COMMANDS:
        error = f"`{cmd}` is not on the read-only allowlist"
    elif cmd == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args):
        error = "sed -i edits files"
    elif cmd == "find" and {"-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint"} & set(args):
        error = "find with an action that runs or deletes"
    return error


def check(command: str) -> str | None:
    # Output redirection writes a file; only discarding to /dev/null is allowed.
    for target in re.findall(r"\d*>>?\s*(\S+)", command):
        if target not in {"/dev/null", "&1", "&2"}:
            return f"redirection to {target} writes a file"
    if re.search(r"\$\(|`", command):
        return "command substitution is not allowed"
    for segment in re.split(r"\|\||&&|;|\||&|\n", command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return "could not parse the command"
        # Leading VAR=value assignments are harmless; the command after them is what runs.
        while tokens and re.fullmatch(r"[A-Za-z_]\w*=.*", tokens[0]):
            tokens = tokens[1:]
        if err := segment_error(tokens):
            return err
    return None


def main() -> None:
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    if err := check(command):
        sys.stderr.write(
            f"Blocked by readonly-bash: {err}. This agent is read-only -- it must not write files, "
            "run the test suite, lint, type-check, or touch services. Say what the caller should run "
            "instead.\n"
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
