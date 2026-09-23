---
paths:
  - "**/app/auth/**"
  - "**/app/api/deps.py"
  - "**/app/api/routers/keys.py"
  - "**/streamlit_app/pages/**"
  - "**/tests/**"
---

# API keys, scopes and test authentication

Path-scoped: loads when a matching file is read. The general rules (`../CLAUDE.md`) and the
cross-cutting contracts (`CLAUDE.md` § Never, § The tenant boundary) still apply.

## Failure contracts

- **An empty `ApiKey.scopes` list means EVERY scope, not none.** Same rule as `expires_at
  IS NULL` meaning never: absent data must mean the pre-existing behaviour, or adding a
  column becomes an outage for every key minted before it. `auth/scopes.py::granted` is the
  one place that reading lives -- resist "fixing" a bare `if not key.scopes`. The consequence
  is that an *omitted* scope list on `POST /v1/keys` is a privilege escalation the `exceeds`
  guard cannot see (it is vacuously satisfied by an empty request), which is why
  `auth/management.py` materialises it into the caller's own scopes before storing.
- **Tests authenticate by overriding `deps.current_principal`, never `current_tenant`.**
  `require_scopes` and `rate_limited` both depend on the principal, so overriding the
  narrower dependency leaves them resolving a real key and every authenticated test gets a
  401 -- which reads as a broken route rather than a broken fixture.
