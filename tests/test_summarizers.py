"""Tests for the model registries in summarizer classes.

These tests don't make network calls — they just check that the model IDs
configured in MODELS dicts haven't drifted from what the providers actually
accept. If a provider deprecates a model, you'd update both the constant
here and the source.
"""
import sys
from types import SimpleNamespace

import omascribe.copilot_auth as copilot_auth
from omascribe.ai_summarizer import (
    AnthropicSummarizer,
    CopilotSummarizer,
    OpenAISummarizer,
    OpenRouterSummarizer,
)


def test_anthropic_haiku_is_current():
    """Haiku tier uses the current claude-haiku-4-5 model ID."""
    haiku = AnthropicSummarizer.MODELS["haiku"]
    assert haiku["id"] == "claude-haiku-4-5-20251001"
    assert "4.5" in haiku["name"]


def test_anthropic_sonnet_is_current():
    """Sonnet tier uses the current claude-sonnet-4-6 model ID."""
    sonnet = AnthropicSummarizer.MODELS["sonnet"]
    assert sonnet["id"] == "claude-sonnet-4-6"
    assert "4.6" in sonnet["name"]


def test_anthropic_no_retired_ids_remain():
    """Guard against reintroducing models Anthropic has retired."""
    retired = {"claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022", "claude-3-7-sonnet-20250219"}
    for tier, info in AnthropicSummarizer.MODELS.items():
        # Real Anthropic IDs use the claude-<family>-<generation> pattern
        assert "claude-" in info["id"], f"{tier} doesn't look like a real Anthropic ID"
        assert info["id"] not in retired, f"{tier} points at a retired Anthropic model"


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


def test_copilot_wired_into_provider_infrastructure(monkeypatch):
    """After merging with #19/#20 the Copilot provider needs to be recognised
    everywhere the shared plumbing looks up providers, or the app happily
    starts in transcription-only safe mode without warning."""
    from omascribe.config import AppConfig, validate_config
    from omascribe.note_maker import CLOUD_PROVIDERS

    assert "copilot" in CLOUD_PROVIDERS, "NoteMaker won't route to Copilot otherwise"

    cfg = AppConfig(ai_provider="copilot", ai_model="mini", github_copilot_token="gho_test")
    assert cfg.provider_api_key() == "gho_test", "AppConfig.provider_api_key must handle copilot's token field"

    monkeypatch.setenv("GITHUB_COPILOT_TOKEN", "gho_env")
    assert AppConfig(ai_provider="copilot", ai_model="mini").provider_api_key() == "gho_env"

    ok, err = validate_config(AppConfig(ai_provider="copilot", ai_model="mini",
                                        github_copilot_token="gho_test"))
    assert ok, f"copilot config should validate, got: {err}"

    ok, err = validate_config(AppConfig(ai_provider="copilot", ai_model="haiku",
                                        github_copilot_token="gho_test"))
    assert not ok and "Copilot" in err, "haiku is not a Copilot tier"


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



# ---------------------------------------------------------------------------
# Truncated responses must fail loudly, not become a half-empty note.
# ---------------------------------------------------------------------------

from omascribe.ai_summarizer import SummaryTruncated  # noqa: E402

GOOD = "OVERVIEW:\nA call.\n\nKEY POINTS:\n- One\n\nACTION ITEMS:\n- None identified\n"


def _openai_like(finish_reason, calls):
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=GOOD))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )
    return create


def _no_sleep(monkeypatch):
    monkeypatch.setattr("omascribe.ai_summarizer.time.sleep", lambda s: None)


def test_openai_truncation_raises_without_retry(monkeypatch):
    import pytest
    _no_sleep(monkeypatch)
    s = OpenAISummarizer(api_key="sk-test")
    calls = []
    s.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_openai_like("length", calls))))
    with pytest.raises(SummaryTruncated):
        s.summarize("hello")
    assert len(calls) == 1


def test_openai_complete_response_parses(monkeypatch):
    s = OpenAISummarizer(api_key="sk-test")
    calls = []
    s.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_openai_like("stop", calls))))
    assert s.summarize("hello").overview == "A call."


def test_anthropic_truncation_raises_and_budget_is_large(monkeypatch):
    import pytest
    _no_sleep(monkeypatch)
    s = AnthropicSummarizer(api_key="sk-ant-test")
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="max_tokens",
            content=[SimpleNamespace(text="OVERVIEW:\nhalf a sen")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=16000),
        )

    s.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    with pytest.raises(SummaryTruncated):
        s.summarize("hello")
    assert len(calls) == 1
    assert calls[0]["max_tokens"] >= 16000


def test_openrouter_truncation_raises(monkeypatch):
    import pytest
    _no_sleep(monkeypatch)
    s = OpenRouterSummarizer.__new__(OpenRouterSummarizer)
    s.model_config = OpenRouterSummarizer.MODELS["balanced"]
    s.model = s.model_config["id"]
    calls = []
    s.client = SimpleNamespace(chat=SimpleNamespace(send=_openai_like("length", calls)))
    with pytest.raises(SummaryTruncated):
        s.summarize("hello")
