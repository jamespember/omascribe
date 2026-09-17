"""Centralized logging configuration for Omascribe application."""

import logging
import os
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler


class PrivateRotatingFileHandler(RotatingFileHandler):
    """Rotating handler that keeps every newly-created log at mode 0600."""

    def _open(self):
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream


def get_log_dir() -> Path:
    """Get the directory for log files."""
    config_home = os.environ.get('XDG_CONFIG_HOME')
    if config_home:
        log_dir = Path(config_home) / "omascribe"
    else:
        log_dir = Path.home() / ".config" / "omascribe"
    
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(log_dir, 0o700)
    return log_dir


# Chatty per-request DEBUG from the HTTP stacks behind the cloud providers.
# Every AssemblyAI poll and every TLS handshake step would otherwise land in
# omascribe.log; warnings and errors from them still come through.
NOISY_LIBRARY_LOGGERS = ("urllib3", "httpx", "httpx2", "httpcore", "httpcore2", "openai", "anthropic")


def setup_logging(debug: bool = False, console: bool = False) -> None:
    """
    Set up application-wide logging.
    
    Creates two log files:
    - errors.log: Only ERROR and CRITICAL messages (always enabled)
    - omascribe.log: All messages including INFO and DEBUG (size-limited rotation)
    
    Args:
        debug: If True, set console output to DEBUG level
        console: Also log to stderr. Off by default because the TUI owns the
            terminal: this handler is created at import time, before Textual
            swaps out sys.stderr, so it keeps the REAL stderr and every INFO
            line is painted straight over the running interface.
    """
    log_dir = get_log_dir()
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything
    
    # Clear any existing handlers to avoid duplicates
    for handler in root_logger.handlers:
        handler.close()
    root_logger.handlers.clear()
    
    # 1. Console handler - INFO or DEBUG depending on debug flag
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        console_formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    for name in NOISY_LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG if debug else logging.WARNING)
    
    # 2. Error file handler - Only errors and above
    error_log = log_dir / "errors.log"
    error_handler = PrivateRotatingFileHandler(error_log, maxBytes=2_000_000, backupCount=2)
    error_handler.setLevel(logging.ERROR)
    error_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s\n'
        'File: %(pathname)s:%(lineno)d\n'
    )
    error_handler.setFormatter(error_formatter)
    root_logger.addHandler(error_handler)
    
    # 3. Full application log - All messages
    app_log = log_dir / "omascribe.log"
    app_handler = PrivateRotatingFileHandler(app_log, maxBytes=5_000_000, backupCount=2)
    app_handler.setLevel(logging.DEBUG)
    app_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    app_handler.setFormatter(app_formatter)
    root_logger.addHandler(app_handler)
    
    # Log startup
    logging.info("="*80)
    logging.info(f"Omascribe application started at {datetime.now()}")
    logging.info(f"Log directory: {log_dir}")
    logging.info(f"Debug mode: {debug}")
    logging.info("="*80)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.
    
    Args:
        name: Usually __name__ of the module
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
