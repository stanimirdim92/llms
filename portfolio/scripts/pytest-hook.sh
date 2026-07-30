#!/usr/bin/env bash
# pre-push hook body for the unit suite. A script rather than an inline `entry:` because the
# logic needs quoting that YAML makes error-prone -- an inline version silently lost its closing
# quote once, which YAML happily accepted and bash then failed on.
#
# Run from the repo root by pre-commit.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

output=$(uv run pytest tests/unit -q 2>&1)
status=$?

if [ "$status" -ne 0 ]; then
  echo "$output" | tail -30
  exit "$status"
fi

echo "$output" | tail -2

# Exit code alone is not enough. The service-backed suites (auth, rate limiting, the job queue)
# *skip* when Postgres or Redis is unreachable, so a green run can mean most of the
# security-relevant surface went untested. Warn loudly rather than failing: a developer without
# the services running should still be able to push a docs change.
if echo "$output" | grep -q "skipped"; then
  echo ""
  echo "WARNING: some tests were skipped, which means Postgres or Redis was unreachable."
  echo "         Auth, rate limiting, and the job queue were NOT exercised by this run."
  echo "         See the 'verify' skill for how to start them."
fi
