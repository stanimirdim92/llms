import importlib
import logging
from collections.abc import Iterator
from types import ModuleType

import pytest

from app.logs import configure_logging


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def transformers_records() -> Iterator[list[logging.LogRecord]]:
    """Records that actually get past the `transformers` logger's filters. A handler on that
    logger, because it does not propagate to the root, so caplog would see nothing either way.
    """
    logger = logging.getLogger("transformers")
    handler = _ListHandler()
    logger.addHandler(handler)
    yield handler.records
    logger.removeHandler(handler)


def _fast_alias_module() -> ModuleType:
    importlib.import_module("transformers")
    return importlib.import_module("transformers.models.beit.image_processing_beit_fast")


def test_streamlit_watcher_probe_of_dunder_on_alias_module_is_silenced(
    transformers_records: list[logging.LogRecord],
) -> None:
    configure_logging()
    module = _fast_alias_module()

    # What Streamlit's LocalSourcesWatcher does to every module on each pass.
    hasattr(module, "__path__")

    assert not [r for r in transformers_records if "Returning" in r.getMessage()]


def test_real_deprecated_fast_class_access_still_warns(
    transformers_records: list[logging.LogRecord],
) -> None:
    configure_logging()
    module = _fast_alias_module()

    module.BeitImageProcessorFast  # noqa: B018 -- the access is the thing under test

    messages = [r.getMessage() for r in transformers_records]
    assert any("BeitImageProcessorFast" in m for m in messages), "a caller on a deprecated name must still be told"
