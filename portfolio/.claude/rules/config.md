---
paths:
  - "**/app/config.py"
  - "**/.env.example"
  - "**/app/api/main.py"
  - "**/app/db.py"
  - "**/app/worker/app.py"
  - "**/.docker/docker-compose.yml"
  - "**/tests/unit/test_cors.py"
  - "**/tests/unit/test_secrets.py"
---

# Settings, credentials and CORS

Path-scoped: loads when a matching file is read. The general rules (`../CLAUDE.md`) and the
cross-cutting contracts (`CLAUDE.md` § Never, § The tenant boundary) still apply.

## Config invariants

- **`cors_allow_credentials` + `"*"` origins is refused at startup.** Starlette answers
  that pair by reflecting the caller's own `Origin` with `Allow-Credentials: true`, so
  every site on the internet becomes trusted. The wildcard default is only inert while
  credentials are off and `cors_allow_headers` is empty. `tests/unit/test_cors.py` pins
  it; don't relax the guard to make a frontend work -- name the origins.
- **`POSTGRES_USER`/`PASSWORD`/`DB` is one set serving two consumers**: the postgres
  image, and `app/config.py`'s `Settings`, which assembles `DATABASE_URL` from them.
  Don't reintroduce a parallel `DB_USER`/`DB_PASSWORD`/`DB_NAME` **for this pair**.
  `APP_DB_USER`/`APP_DB_PASSWORD` (2026-08-07) are not that: a second, deliberately distinct
  role for a different purpose -- see § Row-level security below for why one credential set
  stopped being enough.
- **Every credential in `Settings` is a `SecretStr`**, and `.get_secret_value()` marks each
  point where one escapes (six: four in `config.py`, one each in `db.py` and `worker/app.py` --
  this said eight, and `config.py`'s own copy of the count was wrong too). One object
  holds the Anthropic, Voyage and LangSmith keys plus the Postgres password, so anything that
  renders it renders all four -- and this repository is public. `database_url` is a `SecretStr`
  too: it embeds the password, so masking the password alone was theatre.
  **A `SecretStr` is truthy by length**, so a credential check must read
  `.get_secret_value().strip()` -- a bare `if not value` accepts three spaces as a key and then
  fails every request at the provider, which reads as a revoked key rather than an unset one.
  `tests/unit/test_secrets.py` sweeps every field whose name ends in `_key`/`_password`/
  `_secret`/`_token`, so a new credential added as a plain `str` fails the suite.
