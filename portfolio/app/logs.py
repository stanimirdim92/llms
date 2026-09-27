"""structlog configuration. The rest of the app already calls
`structlog.get_logger(__name__)` (see `generation/answer_service.py`,
`ingestion/pipeline.py`) -- this is what actually configures how those calls render;
nothing did before, so they were running on structlog's unconfigured defaults.

Also routes stdlib `logging` through the same structlog processors/renderer, since
uvicorn's access logs and various dependencies (LangChain, etc.) log via stdlib
`logging`, not structlog -- without this they'd render in a visibly different format
right next to our own structured lines.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import get_settings

_ALIAS_WARNING_PREFIX = "Accessing `%s` from `%s`. Returning `%s` instead."


def _drop_transformers_dunder_alias_warning(record: logging.LogRecord) -> bool:
    """Streamlit's file watcher probes `__path__` on every module in `sys.modules` on each
    pass, and transformers 5 warns on every probe of its `*_fast` compat aliases -- a wall of
    noise per rerun. Only dunder probes are dropped: a real `XImageProcessorFast` access still
    warns, because that one means a caller is on a deprecated name.
    """
    if not (isinstance(record.msg, str) and record.msg.startswith(_ALIAS_WARNING_PREFIX)):
        return True
    name = record.args[0] if isinstance(record.args, tuple) and record.args else ""
    return not (isinstance(name, str) and name.startswith("__") and name.endswith("__"))


def configure_logging(*, json_logs: bool | None = None, level: str | None = None) -> None:
    """Call once per process at startup: `api/main.py`, `streamlit_app/Home.py`, and
    each of `scripts/*.py` are each their own process. Safe to call more than once
    (e.g. Streamlit re-executes the whole script on every rerun) -- this replaces the
    root logger's handlers rather than appending to them.
    """
    settings = get_settings()
    json_logs = settings.log_json if json_logs is None else json_logs
    log_level = getattr(logging, (level or settings.log_level).upper())

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # On the `transformers` logger itself, not the root: it has its own handler and does not
    # propagate, so a root filter never sees the record. addFilter dedupes, so reruns are safe.
    logging.getLogger("transformers").addFilter(_drop_transformers_dunder_alias_warning)
