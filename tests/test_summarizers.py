"""Tests for the model registries in summarizer classes.

These tests don't make network calls — they just check that the model IDs
configured in MODELS dicts haven't drifted from what the providers actually
accept. If a provider deprecates a model, you'd update both the constant
here and the source.
"""
import sys
from types import SimpleNamespace

import meeting_notes.copilot_auth as copilot_auth
from meeting_notes.ai_summarizer import (
    AnthropicSummarizer,
    CopilotSummarizer,
    OpenAISummarizer,
    OpenRouterSummarizer,
)


def test_anthropic_haiku_is_current_4_5():
    """eduspano/jmalobicky bumped Haiku from 3.5 to 4.5."""
    haiku = AnthropicSummarizer.MODELS["haiku"]
    assert haiku["id"] == "claude-haiku-4-5-20251001"
    assert "4.5" in haiku["name"]


def test_anthropic_sonnet_is_current_4_6():
    """eduspano bumped Sonnet to 4.6."""
    sonnet = AnthropicSummarizer.MODELS["sonnet"]
    assert sonnet["id"] == "claude-sonnet-4-6"
    assert "4.6" in sonnet["name"]


def test_anthropic_no_deprecated_3_5_ids_remain():
    """Guard against accidental revert to deprecated 3.5 model IDs."""
    for tier, info in AnthropicSummarizer.MODELS.items():
        assert "3-5" not in info["id"], f"{tier} still references deprecated 3.5 model"
        assert "3.5" not in info["name"], f"{tier} still labelled as 3.5"


def test_anthropic_models_have_required_fields():
    for tier, info in AnthropicSummarizer.MODELS.items():
        for field in ("id", "name", "cost_per_1k_input", "cost_per_1k_output"):
            assert field in info, f"Anthropic {tier} missing {field}"
        assert isinstance(info["cost_per_1k_input"], (int, float))


def test_openai_models_have_required_fields():
    for tier, info in OpenAISummarizer.MODELS.items():
        for field in ("id", "name", "cost_per_1k_input", "cost_per_1k_output"):
            assert field in info, f"OpenAI {tier} missing {field}"


def test_openrouter_models_have_required_fields():
    for tier, info in OpenRouterSummarizer.MODELS.items():
        for field in ("id", "name"):
            assert field in info, f"OpenRouter {tier} missing {field}"


def test_copilot_summarizer_exchanges_oauth_token_for_session_token(monkeypatch):
    created_clients = []

    class FakeTokenManager:
        def __init__(self, github_token):
            self.github_token = github_token
            self.invalidated = False

        def get_token(self):
            return "copilot-session-token"

        def invalidate(self):
            self.invalidated = True

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created_clients.append(kwargs)

    monkeypatch.setattr(copilot_auth, "CopilotTokenManager", FakeTokenManager)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    summarizer = CopilotSummarizer(api_key="github-oauth-token", model="mini")
    client = summarizer._get_client()

    assert client is not None
    assert summarizer._token_manager.github_token == "github-oauth-token"
    assert created_clients[0]["api_key"] == "copilot-session-token"
    assert created_clients[0]["api_key"] != "github-oauth-token"
    assert created_clients[0]["base_url"] == "https://api.githubcopilot.com"


def test_copilot_models_have_required_fields():
    for tier, info in CopilotSummarizer.MODELS.items():
        for field in ("id", "name"):
            assert field in info, f"Copilot {tier} missing {field}"


def test_anthropic_summarizer_requires_api_key(monkeypatch):
    """Without an API key (and no env var), construction should fail clearly."""
    import pytest
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        AnthropicSummarizer(api_key=None, model="haiku")


def test_anthropic_summarizer_rejects_unknown_model():
    """Unknown model tier should not be silently accepted."""
    import pytest
    with pytest.raises((KeyError, ValueError)):
        AnthropicSummarizer(api_key="sk-ant-test", model="not-a-tier")
