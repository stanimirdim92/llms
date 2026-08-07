"""Structural enforcement of the tenant boundary: `DocumentRecord` is queried -- `select`,
`update`, `delete`, or `Session.get` -- from exactly one module, or row-level security
(migration `a4f8c1d92e07`) is the only thing standing between a new, unscoped query and a
cross-tenant leak.

No live Postgres needed -- this is a source-level check, and that's the point. RLS is a runtime
backstop for a query that already exists and forgot its filter; this catches a *new* query
built outside `app/registry/db.py` before it ships, the same way `test_upload_formats.py`
catches the ingestion stack leaking into the api process. Both are "a new file can quietly
reintroduce a removed constraint"; neither is a test a reviewer's attention should have to
catch by itself.

Deliberately does NOT flag every reference to `DocumentRecord` -- constructing one to pass to
`stage_document_record`/`save_document_record` (`documents.py`, `streamlit_app/Home.py`) and
type-hinting an already-tenant-scoped list a caller received (`document_scope.py`) are both
legitimate and outside this file's job. Only a call that *queries the table* is the risk.
"""

from __future__ import annotations

import ast
from pathlib import Path

PORTFOLIO_ROOT = Path(__file__).resolve().parent.parent.parent

# The one place allowed to query DocumentRecord. `models.py` defines the class -- referencing it
# there is definitional, not a query -- and every select/update/delete/get against it belongs
# in `db.py`, which is what makes it reviewable as a unit.
_ALLOWED_MODULE = PORTFOLIO_ROOT / "app" / "registry" / "db.py"

# Fixtures build DocumentRecord rows directly to seed a test database, which is a different
# question from whether a *query* is tenant-scoped, and Alembic revisions never reference the
# model class at all (columns are strings, by design -- migrations outlive any particular model
# shape). Both out of scope here.
_EXEMPT_DIRS = (PORTFOLIO_ROOT / "tests", PORTFOLIO_ROOT / "migrations")

_QUERY_CALLS = {"select", "update", "delete"}  # sqlmodel/sqlalchemy statement builders
_QUERY_METHODS = {"get", "get_one"}  # AsyncSession.get(Model, pk) -- no WHERE clause to filter


def _document_record_queries(path: Path) -> list[int]:
    """Line numbers where `path` queries `DocumentRecord` directly: `select(DocumentRecord)`,
    `update(DocumentRecord)`, `delete(DocumentRecord)`, or `session.get(DocumentRecord, ...)`.

    AST-based, not a text grep, so a match inside a string literal or this docstring's own
    examples doesn't trip a false positive.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        target = node.args[0]
        if not (isinstance(target, ast.Name) and target.id == "DocumentRecord"):
            continue
        func = node.func
        is_query_call = isinstance(func, ast.Name) and func.id in _QUERY_CALLS
        is_query_method = isinstance(func, ast.Attribute) and func.attr in _QUERY_METHODS
        if is_query_call or is_query_method:
            hits.append(node.lineno)
    return hits


def test_documentrecord_is_queried_from_exactly_one_module() -> None:
    """A router, a script, or a helper that builds its own `select(DocumentRecord)` can write
    any filter it wants, including none -- row-level security would still stop that from
    leaking rows, but a query that never scopes to the right tenant is a functional bug
    regardless of RLS, and RLS existing is not a reason to stop catching this the cheap way.

    Fails loudly with the offending path and line rather than a bare assertion, since the fix
    (route the caller through `app/registry/db.py` instead) is the same every time and worth
    stating once here rather than re-deriving it from a stack trace.
    """
    offenders = {
        f"{path.relative_to(PORTFOLIO_ROOT)}:{line}"
        for path in PORTFOLIO_ROOT.rglob("*.py")
        if path != _ALLOWED_MODULE and ".venv" not in path.parts and not any(d in path.parents for d in _EXEMPT_DIRS)
        for line in _document_record_queries(path)
    }
    assert not offenders, (
        f"{sorted(offenders)} query DocumentRecord directly. Add a tenant-scoped function to "
        f"app/registry/db.py and call that instead -- see get_document_record for the pattern."
    )
