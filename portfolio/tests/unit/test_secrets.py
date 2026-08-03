"""Credentials in `Settings` are `SecretStr`, and the boot check reads their contents.

Two separate properties, and they pull in opposite directions, which is why both are pinned
here. The masking must hold for anything that renders the object -- this repository is public,
and `Settings` carries a live Anthropic key, a Voyage key, a LangSmith key and the Postgres
password, so one `log.info(..., settings=settings)` written while debugging discloses all four.
The credential check must nonetheless look *through* the mask, because `SecretStr` is truthy by
length: a key of three spaces passes any bare truthiness test and then fails every request with
a 401 from the provider, which reads as a revoked key rather than an unset one.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app import config
from app.config import MissingCredentialsError, Settings, require_provider_credentials


def _settings(  # noqa: PLR0913 -- one keyword per Settings field a test overrides; see below
    *,
    anthropic_api_key: str = "",
    voyage_api_key: str = "",
    postgres_password: str = "portfolio",
    postgres_user: str = "portfolio",
    postgres_db: str = "portfolio",
    redis_password: str = "",
    redis_host: str = "localhost",
    redis_port: int = 6379,
) -> Settings:
    """A `Settings` built without reading `.env`.

    `_env_file=None` matters: this repository's own `.env` holds a real LangSmith key, so a
    test that constructed `Settings()` normally would assert against whatever the developer
    happens to have configured, and pass or fail for reasons unrelated to the code.

    Keywords spelled out rather than `**overrides: object`, which is what this started as: with
    a loose `object` value, every `SecretStr`/`Literal`/`int` field on `Settings` reports an
    argument-type error, and `ty check` produced 76 diagnostics from this one line.
    """
    return Settings(
        _env_file=None,
        anthropic_api_key=SecretStr(anthropic_api_key),
        voyage_api_key=SecretStr(voyage_api_key),
        postgres_password=SecretStr(postgres_password),
        postgres_user=postgres_user,
        postgres_db=postgres_db,
        redis_password=SecretStr(redis_password),
        redis_host=redis_host,
        redis_port=redis_port,
    )


def test_a_key_never_appears_in_the_repr() -> None:
    """The accident this exists for: a repr reaches a log, a traceback frame, or a crash
    reporter. `SecretStr.__repr__` is `SecretStr('**********')`, so all four secrets are masked
    at once rather than each call site having to remember.
    """
    settings = _settings(anthropic_api_key="sk-ant-not-a-real-key", postgres_password="hunter2")

    rendered = repr(settings)

    assert "sk-ant-not-a-real-key" not in rendered
    assert "hunter2" not in rendered
    assert "**********" in rendered


def test_a_key_never_appears_in_a_model_dump() -> None:
    """`model_dump()` is the other renderer -- structlog's processors call it on anything
    dict-like, and a JSON log line is exactly where a key gets shipped to a log aggregator.
    """
    dumped = _settings(voyage_api_key="pa-secret").model_dump()

    assert "pa-secret" not in str(dumped)


def test_the_real_value_is_still_reachable_where_it_is_needed() -> None:
    """Masking must not become "the key is gone". `.get_secret_value()` is the deliberate,
    greppable marker of the places a secret genuinely escapes -- URL assembly and the LangSmith
    env bridge.
    """
    assert _settings(anthropic_api_key="sk-ant-x").anthropic_api_key.get_secret_value() == "sk-ant-x"


def test_the_assembled_database_url_carries_the_real_password() -> None:
    """The DSN is handed to psycopg, so a masked password here would fail at connect time with
    an authentication error naming nothing -- the one place where masking would be a bug.
    """
    url = _settings(postgres_password="hunter2", postgres_user="portfolio", postgres_db="portfolio").database_url

    assert "hunter2" in url.get_secret_value()


def test_the_redis_url_omits_credentials_entirely_when_none_are_set() -> None:
    """An empty password must produce `redis://host:port/db`, not `redis://:@host:port/db`.
    The second form is a *different* URL: redis-py sends an AUTH with an empty username and
    password, and a server with no password configured rejects it.
    """
    assert _settings(redis_password="", redis_host="localhost", redis_port=6379).redis_url == "redis://localhost:6379/0"


def test_a_whitespace_only_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reason the check calls `.get_secret_value().strip()` rather than testing truthiness.
    `SecretStr("   ")` is truthy -- it has length -- so a bare `if not value` would let a key
    of spaces through boot and fail every subsequent request at the provider.
    """
    settings = config.get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("   "))
    monkeypatch.setattr(settings, "voyage_api_key", SecretStr("pa-real"))

    with pytest.raises(MissingCredentialsError, match="ANTHROPIC_API_KEY"):
        require_provider_credentials()


def test_both_missing_keys_are_named_in_one_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reporting one at a time means two failed boots to learn about two unset variables."""
    settings = config.get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "voyage_api_key", SecretStr(""))

    with pytest.raises(MissingCredentialsError, match="ANTHROPIC_API_KEY and VOYAGE_API_KEY"):
        require_provider_credentials()


def test_configured_keys_pass_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half: this runs in the api's lifespan, so a false positive here refuses to
    start a correctly configured service.
    """
    settings = config.get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("sk-ant-x"))
    monkeypatch.setattr(settings, "voyage_api_key", SecretStr("pa-x"))

    require_provider_credentials()  # must not raise
