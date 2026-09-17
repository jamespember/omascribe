"""Tests for private logs and complete credential redaction."""

import logging

from omascribe.config import AppConfig
from omascribe import logger


def test_api_keys_are_fully_redacted():
    config = AppConfig(anthropic_api_key="sk-ant-secret-value")
    safe = config.to_safe_dict()
    assert safe["anthropic_api_key"] == "[redacted]"
    assert "secret" not in str(safe)


def test_log_files_are_private(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    logger.setup_logging()

    log_dir = tmp_path / "omascribe"
    assert log_dir.stat().st_mode & 0o777 == 0o700
    assert (log_dir / "omascribe.log").stat().st_mode & 0o777 == 0o600
    assert (log_dir / "errors.log").stat().st_mode & 0o777 == 0o600

    for handler in logging.getLogger().handlers:
        handler.close()


def test_tui_logging_never_writes_to_the_terminal(tmp_path, monkeypatch):
    """A stderr handler paints log lines over the running Textual UI."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    logger.setup_logging()
    try:
        streams = [h for h in logging.getLogger().handlers
                   if type(h) is logging.StreamHandler]
        assert streams == []
        assert logging.getLogger("urllib3").level == logging.WARNING
    finally:
        for handler in logging.getLogger().handlers:
            handler.close()
