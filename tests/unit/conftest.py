import logging

import pytest

from oria_engine.config import Settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)
    loggers = [
        logging.getLogger(name) for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    ]
    saved = [(logger, logger.handlers[:], logger.level, logger.propagate) for logger in loggers]
    yield
    for logger, handlers, level, propagate in saved:
        logger.handlers = handlers
        logger.setLevel(level)
        logger.propagate = propagate
