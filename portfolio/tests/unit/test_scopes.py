"""The permission vocabulary, and the route-to-scope map.

Two halves. The first tests `auth/scopes.py` as pure functions -- no database, no request --
because every authorization decision in the API reduces to them. The second walks the real
route table and asserts which scope each route requires, which is the assertion a newly added
route silently falsifies: `require_scopes` is declared per route, so one registered without it
is reachable by any key and nothing raises.
"""

from __future__ import annotations

from app.api.main import app
from app.auth.scopes import (
    ALL_SCOPES,
    ASK,
    DOCUMENTS_READ,
    DOCUMENTS_WRITE,
    KEYS_READ,
    KEYS_WRITE,
    UNRESTRICTED,
    exceeds,
    granted,
    has_scope,
    unknown_scopes,
)

EXPECTED_ROUTE_SCOPES = {
    ("/v1/ask", "POST"): (ASK,),
    ("/v1/documents", "POST"): (DOCUMENTS_WRITE,),
    ("/v1/documents", "GET"): (DOCUMENTS_READ,),
    ("/v1/documents/{doc_id}", "GET"): (DOCUMENTS_READ,),
    ("/v1/keys", "POST"): (KEYS_WRITE,),
    ("/v1/keys", "GET"): (KEYS_READ,),
    ("/v1/keys/{key_id}", "DELETE"): (KEYS_WRITE,),
}
"""Every authenticated route and the scope it demands. Health probes are absent on purpose --
they are unauthenticated, and `test_no_probe_requires_a_scope` pins that separately."""


def _declared_scopes() -> dict[tuple[str, str], tuple[str, ...]]:
    """Walk the app's routes and read back what each `require_scopes` closure enforces.

    Reads the `required_scopes` attribute `deps.require_scopes` attaches, rather than picking
    apart the closure's cells -- the attribute exists precisely so this is a supported read.
    """
    found: dict[tuple[str, str], tuple[str, ...]] = {}

    def walk(routes: list, prefix: str) -> None:
        # Recursive, and it has to be. `include_router` does not splice routes into
        # `app.routes` on current FastAPI -- it appends one `_IncludedRouter` per call, holding
        # the original router and the prefix it was mounted under. A flat pass therefore finds
        # four opaque wrappers and exactly one real route, and every assertion phrased as
        # "no route is missing a scope" passes while checking nothing.
        for route in routes:
            if included := getattr(route, "original_router", None):
                walk(included.routes, prefix + route.include_context.prefix)
                continue
            if nested := getattr(route, "routes", None):  # pre-_IncludedRouter FastAPI
                walk(nested, prefix)
                continue
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            scopes: tuple[str, ...] = ()
            for dependency in dependant.dependencies:
                scopes += getattr(dependency.call, "required_scopes", ())
            for method in getattr(route, "methods", set()):
                found[prefix + route.path, method] = scopes

    walk(app.routes, "")
    return found


def test_every_route_requires_the_scope_it_should() -> None:
    declared = _declared_scopes()

    for route_key, expected in EXPECTED_ROUTE_SCOPES.items():
        assert declared.get(route_key) == expected, f"{route_key} requires {declared.get(route_key)}, not {expected}"


def test_no_authenticated_route_is_missing_a_scope() -> None:
    """The half of the map an added route breaks. The dictionary above only proves the routes
    someone remembered to list; this proves nothing else under `/v1` slipped through with no
    requirement at all.
    """
    unscoped = [key for key, scopes in _declared_scopes().items() if key[0].startswith("/v1") and not scopes]

    assert not unscoped, f"routes under /v1 with no required scope: {unscoped}"


def test_no_probe_requires_a_scope() -> None:
    """An orchestrator cannot send an API key, so a scoped probe takes the service out of
    rotation the moment it is added.
    """
    declared = _declared_scopes()

    assert not declared.get(("/health/live", "GET"))
    assert not declared.get(("/health/ready", "GET"))


def test_an_empty_scope_list_confers_everything() -> None:
    """The load-bearing back-compatibility rule, and the one most likely to be "fixed" by
    someone reading `if not key.scopes` as a denial. Keys minted before the column existed
    have no list; the other reading revokes all of them the moment it ships.
    """
    assert granted(UNRESTRICTED) == frozenset(ALL_SCOPES)
    assert granted(None) == frozenset(ALL_SCOPES)
    assert all(has_scope(UNRESTRICTED, scope) for scope in ALL_SCOPES)


def test_a_populated_scope_list_confers_only_itself() -> None:
    assert has_scope([ASK], ASK)
    assert not has_scope([ASK], DOCUMENTS_WRITE)


def test_unknown_scopes_are_reported_in_the_order_given() -> None:
    assert unknown_scopes(["documents:wrote", ASK, "admin"]) == ["documents:wrote", "admin"]
    assert unknown_scopes(list(ALL_SCOPES)) == []


def test_a_key_cannot_confer_what_it_does_not_hold() -> None:
    assert exceeds([DOCUMENTS_WRITE], [DOCUMENTS_READ]) == [DOCUMENTS_WRITE]
    assert exceeds([DOCUMENTS_READ], [DOCUMENTS_READ, ASK]) == []


def test_an_unrestricted_key_can_confer_anything() -> None:
    """Follows from `granted`, and is intended: it is what the human-minted bootstrap key
    from `scripts/create_tenant.py` is for.
    """
    assert exceeds(list(ALL_SCOPES), UNRESTRICTED) == []


def test_requesting_nothing_never_looks_like_escalation() -> None:
    """`exceeds` is vacuously satisfied by an empty request, which is why the create route
    must materialise an omitted list into the caller's own scopes rather than storing it
    empty -- empty means *unrestricted*, so storing it would be the escalation this function
    cannot see. `test_api_contract.py` covers the route; this pins why it has to.
    """
    assert exceeds([], [KEYS_WRITE]) == []
