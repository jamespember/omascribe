"""Shared pytest fixtures and config."""
import logging
import os
import sys
import tempfile
from pathlib import Path

# Ensure repo root is importable so `import omascribe...` works
# regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Scrub real API keys from the environment so tests can't accidentally
# make real network calls (and so individual tests can monkeypatch them
# back without interference). Tests that need a key should provide a
# fake one explicitly via monkeypatch.setenv.
for key in (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "ASSEMBLYAI_API_KEY",
    "DEEPINFRA_API_KEY",
    "GITHUB_COPILOT_TOKEN",
):
    os.environ.pop(key, None)

# Redirect XDG_CONFIG_HOME to a throwaway tempdir BEFORE any omascribe
# module imports happen. Previously, the transcriber/recorder tests that
# deliberately raise exceptions had their tracebacks logged into the
# user's real ~/.config/omascribe/errors.log, polluting it with stale
# pytest output and making it useless for actual debugging. Pinning XDG to
# a tempdir for the test session means logger.py:get_log_dir() resolves
# to a tmp path, and the user's real logs stay clean.
_test_xdg = tempfile.mkdtemp(prefix="omascribe-pytest-xdg-")
os.environ["XDG_CONFIG_HOME"] = _test_xdg
os.environ["XDG_STATE_HOME"] = str(Path(_test_xdg) / "state")
os.environ["XDG_RUNTIME_DIR"] = str(Path(_test_xdg) / "runtime")
os.environ["MEETING_NOTES_DISABLE_DESKTOP_NOTIFICATIONS"] = "1"

# Silence the omascribe loggers for tests by default. Individual tests
# that want to assert on log output can still configure their own handlers.
# This is belt-and-braces alongside the XDG redirect above.
logging.getLogger("omascribe").setLevel(logging.CRITICAL)
