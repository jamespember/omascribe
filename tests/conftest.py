"""Shared pytest fixtures and config."""
import logging
import os
import sys
import tempfile
from pathlib import Path

# Ensure repo root is importable so `import meeting_notes...` works
# regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Scrub real API keys from the environment so tests can't accidentally
# make real network calls (and so individual tests can monkeypatch them
# back without interference). Tests that need a key should provide a
# fake one explicitly via monkeypatch.setenv.
for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GITHUB_COPILOT_TOKEN"):
    os.environ.pop(key, None)

# Redirect XDG_CONFIG_HOME to a throwaway tempdir BEFORE any meeting_notes
# module imports happen. Previously, the transcriber/recorder tests that
# deliberately raise exceptions had their tracebacks logged into the
# user's real ~/.config/meeting-notes/errors.log, polluting it with stale
# pytest output and making it useless for actual debugging. Pinning XDG to
# a tempdir for the test session means logger.py:get_log_dir() resolves
# to a tmp path, and the user's real logs stay clean.
_test_xdg = tempfile.mkdtemp(prefix="meeting-notes-pytest-xdg-")
os.environ["XDG_CONFIG_HOME"] = _test_xdg

# Silence the meeting_notes loggers for tests by default. Individual tests
# that want to assert on log output can still configure their own handlers.
# This is belt-and-braces alongside the XDG redirect above.
logging.getLogger("meeting_notes").setLevel(logging.CRITICAL)
