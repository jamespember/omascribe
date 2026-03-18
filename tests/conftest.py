"""Shared pytest fixtures and config."""
import os
import sys
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
