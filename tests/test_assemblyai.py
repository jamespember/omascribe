"""Tests for the AssemblyAI transcriber and LLM Gateway summarizer.

No network: the transcriber takes an injected session, and the summarizer's
OpenAI client is swapped for a fake after construction.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from omascribe.ai_summarizer import AssemblyAISummarizer, DeepInfraSummarizer
from omascribe.config import AppConfig, validate_config
from omascribe.note_maker import NoteMaker
from omascribe.transcriber import (
    AssemblyAIError,
    AssemblyAITranscriber,
    WhisperTranscriber,
    build_transcriber,
    format_segments,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, polls):
        self.headers = {}
        self.posts = []
        self.gets = []
        self._polls = list(polls)

    def post(self, url, data=None, json=None, timeout=None):
        self.posts.append((url, json))
        if url.endswith("/v2/upload"):
            data.read()
            return FakeResponse(payload={"upload_url": "https://cdn.example/abc"})
        return FakeResponse(payload={"id": "tx1", "status": "queued"})

    def get(self, url, timeout=None):
        self.gets.append(url)
        return self._polls.pop(0)


COMPLETED = {
    "status": "completed",
    "text": "Hello there. I'll send the doc.",
    "language_code": "en",
    "audio_duration": 12,
    "utterances": [
        {"speaker": "A", "start": 0, "end": 1500, "text": "Hello there."},
        {"speaker": "B", "start": 61000, "end": 64000, "text": "I'll send the doc."},
    ],
}


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "meeting.wav"
    path.write_bytes(b"RIFF....WAVE")
    return path


def test_transcribe_uploads_requests_speakers_and_polls(audio, monkeypatch):
    monkeypatch.setattr(AssemblyAITranscriber, "POLL_INTERVAL", 0)
    session = FakeSession([FakeResponse(payload={"status": "processing"}), FakeResponse(payload=COMPLETED)])
    t = AssemblyAITranscriber(api_key="key123", session=session)

    result = t.transcribe(str(audio))

    assert session.headers["authorization"] == "key123"  # raw key, no Bearer
    request = session.posts[1][1]
    assert request["audio_url"] == "https://cdn.example/abc"
    assert request["speaker_labels"] is True
    assert request["speech_models"][0] == "universal-3-5-pro"
    assert len(session.gets) == 2
    assert [s.speaker for s in result.segments] == ["A", "B"]
    assert result.segments[1].start == 61.0
    assert result.duration == 12.0
    assert result.language == "en"


def test_speaker_text_and_formatting(audio, monkeypatch):
    monkeypatch.setattr(AssemblyAITranscriber, "POLL_INTERVAL", 0)
    result = AssemblyAITranscriber(api_key="k", session=FakeSession([FakeResponse(payload=COMPLETED)])).transcribe(str(audio))

    assert result.speaker_text() == "Speaker A: Hello there.\nSpeaker B: I'll send the doc."
    assert format_segments(result.segments) == (
        "**[00:00] Speaker A:** Hello there.\n\n**[01:01] Speaker B:** I'll send the doc."
    )


def test_transcription_error_surfaces_api_message(audio, monkeypatch):
    monkeypatch.setattr(AssemblyAITranscriber, "POLL_INTERVAL", 0)
    session = FakeSession([FakeResponse(payload={"status": "error", "error": "Audio file is empty"})])
    with pytest.raises(AssemblyAIError, match="Audio file is empty"):
        AssemblyAITranscriber(api_key="k", session=session).transcribe(str(audio))


def test_http_error_includes_status(audio):
    session = FakeSession([])
    session.post = lambda *a, **k: FakeResponse(401, {"error": "Invalid API key"})
    with pytest.raises(AssemblyAIError, match="401.*Invalid API key"):
        AssemblyAITranscriber(api_key="bad", session=session).transcribe(str(audio))


def test_missing_key_fails_at_transcribe_not_construction(audio):
    t = AssemblyAITranscriber(api_key=None, session=FakeSession([]))
    with pytest.raises(ValueError, match="ASSEMBLYAI_API_KEY"):
        t.transcribe(str(audio))


def test_build_transcriber_follows_config():
    assert isinstance(build_transcriber(AppConfig()), WhisperTranscriber)
    assert isinstance(build_transcriber(AppConfig(transcriber="assemblyai")), AssemblyAITranscriber)


def test_whisper_segments_render_without_speaker():
    from omascribe.transcriber import TranscriptSegment
    assert format_segments([TranscriptSegment(5, 6, " hi ")]) == "**[00:05]** hi"


def test_validate_accepts_assemblyai(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "k")
    cfg = AppConfig(ai_provider="assemblyai", ai_model="sonnet", transcriber="assemblyai")
    assert validate_config(cfg) == (True, None)
    assert cfg.provider_api_key() == "k"


def test_validate_rejects_bad_transcriber_and_model():
    ok, err = validate_config(AppConfig(transcriber="vosk"))
    assert not ok and "transcriber" in err
    ok, err = validate_config(AppConfig(ai_provider="assemblyai", ai_model="balanced"))
    assert not ok and "AssemblyAI" in err


def test_safe_dict_redacts_assemblyai_key():
    assert AppConfig(assemblyai_api_key="secret").to_safe_dict()["assemblyai_api_key"] == "[redacted]"


def test_summarizer_uses_gateway_and_parses(monkeypatch):
    s = AssemblyAISummarizer(api_key="k", model="sonnet")
    assert str(s.client.base_url).startswith("https://llm-gateway.assemblyai.com/v1")
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        content = "OVERVIEW:\nA call.\n\nKEY POINTS:\n- Doc\n\nACTION ITEMS:\n- Speaker B to send the doc\n\nDECISIONS:\n- None identified\n\nPARTICIPANTS:\nSpeaker A, Speaker B\n"
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )

    s.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    summary = s.summarize("Speaker B: I'll send the doc.")

    assert calls[0]["model"] == "claude-sonnet-5"
    assert "temperature" not in calls[0]
    assert "Speaker B: I'll send the doc." in calls[0]["messages"][0]["content"]
    assert summary.action_items == ["Speaker B to send the doc"]


def test_summarizer_requires_key():
    with pytest.raises(ValueError, match="ASSEMBLYAI_API_KEY"):
        AssemblyAISummarizer(api_key=None)


def test_note_maker_summarises_speaker_text(tmp_path):
    maker = NoteMaker(output_dir=str(tmp_path / "n"), transcripts_dir=str(tmp_path / "t"),
                      ai_provider="assemblyai", ai_model="haiku", api_key="k")
    seen = []
    maker.summarizer = SimpleNamespace(summarize=lambda text, user_notes="": seen.append(text) or (_ for _ in ()).throw(RuntimeError("stop")))
    maker.create_note(transcript_text="plain words", formatted_transcript="", duration=1,
                      title="T", summary_input="Speaker A: plain words")
    assert seen == ["Speaker A: plain words"]


def test_deepinfra_summarizer_targets_deepinfra_claude(monkeypatch):
    monkeypatch.setenv("DEEPINFRA_API_KEY", "di-key")
    s = DeepInfraSummarizer(model="opus")
    assert str(s.client.base_url).startswith("https://api.deepinfra.com/v1/openai")
    assert s.model == "anthropic/claude-opus-5"
    assert s.api_key == "di-key"


def test_deepinfra_requires_its_own_key(monkeypatch):
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "not-this-one")
    with pytest.raises(ValueError, match="DEEPINFRA_API_KEY"):
        DeepInfraSummarizer()


def test_validate_accepts_deepinfra_with_assemblyai_transcription(monkeypatch):
    monkeypatch.setenv("DEEPINFRA_API_KEY", "k")
    cfg = AppConfig(ai_provider="deepinfra", ai_model="sonnet", transcriber="assemblyai")
    assert validate_config(cfg) == (True, None)
    assert cfg.provider_api_key() == "k"
    ok, err = validate_config(AppConfig(ai_provider="deepinfra", ai_model="premium"))
    assert not ok and "DeepInfra" in err


def test_note_maker_builds_deepinfra(tmp_path):
    maker = NoteMaker(output_dir=str(tmp_path / "n"), transcripts_dir=str(tmp_path / "t"),
                      ai_provider="deepinfra", ai_model="haiku", api_key="k")
    assert isinstance(maker.summarizer, DeepInfraSummarizer)
    assert maker.ai_provider == "deepinfra"


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="needs ffmpeg")
def test_upload_is_compressed_to_16k_mono_flac(tmp_path, monkeypatch):
    import subprocess, wave
    wav = tmp_path / "long.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(b"\x01\x02" * 2 * 48000)  # 1 s of stereo 48 kHz
    monkeypatch.setattr(AssemblyAITranscriber, "POLL_INTERVAL", 0)
    session = FakeSession([FakeResponse(payload=COMPLETED)])
    uploaded = {}
    original_post = session.post
    def post(url, data=None, json=None, timeout=None):
        if url.endswith("/v2/upload"):
            uploaded["name"] = data.name
            uploaded["head"] = data.read(4)
            return FakeResponse(payload={"upload_url": "u"})
        return original_post(url, data=data, json=json, timeout=timeout)
    session.post = post
    AssemblyAITranscriber(api_key="k", session=session).transcribe(str(wav))
    assert uploaded["name"].endswith(".flac") and uploaded["head"] == b"fLaC"
    assert wav.exists(), "the original recording is never touched"


def test_upload_retries_a_dropped_connection(audio, monkeypatch):
    import requests
    monkeypatch.setattr(AssemblyAITranscriber, "POLL_INTERVAL", 0)
    monkeypatch.setattr("omascribe.transcriber.time.sleep", lambda s: None)
    session = FakeSession([FakeResponse(payload=COMPLETED)])
    original_post = session.post
    calls = {"n": 0}
    def post(url, data=None, json=None, timeout=None):
        if url.endswith("/v2/upload"):
            calls["n"] += 1
            if calls["n"] < 3:
                raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")
        return original_post(url, data=data, json=json, timeout=timeout)
    session.post = post
    result = AssemblyAITranscriber(api_key="k", session=session).transcribe(str(audio))
    assert calls["n"] == 3 and result.segments


def test_upload_gives_up_with_a_clear_error(audio, monkeypatch):
    import requests
    monkeypatch.setattr("omascribe.transcriber.time.sleep", lambda s: None)
    session = FakeSession([])
    def post(url, data=None, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("reset")
    session.post = post
    with pytest.raises(AssemblyAIError, match="after 3 attempts"):
        AssemblyAITranscriber(api_key="k", session=session).transcribe(str(audio))


def _fake_client(finish_reason, content, calls):
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_truncated_summary_is_an_error_not_a_note(monkeypatch):
    from omascribe.ai_summarizer import SummaryTruncated
    monkeypatch.setattr("omascribe.ai_summarizer.time.sleep", lambda s: None)
    s = DeepInfraSummarizer(api_key="k")
    calls = []
    s.client = _fake_client("length", "", calls)
    with pytest.raises(SummaryTruncated, match="output limit"):
        s.summarize("Speaker A: hi")
    assert len(calls) == 1, "not retried: the same request truncates the same way"


def test_output_budget_leaves_room_for_reasoning():
    s = DeepInfraSummarizer(api_key="k")
    calls = []
    s.client = _fake_client("stop", "OVERVIEW:\nok\n", calls)
    s.summarize("Speaker A: hi")
    assert calls[0]["max_tokens"] >= 16000


def test_transcribe_is_submit_then_wait(audio, monkeypatch):
    monkeypatch.setattr(AssemblyAITranscriber, "POLL_INTERVAL", 0)
    t = AssemblyAITranscriber(api_key="k", session=FakeSession([FakeResponse(payload=COMPLETED)]))
    transcript_id = t.submit(str(audio))
    assert transcript_id == "tx1"
    assert [s.speaker for s in t.wait(transcript_id).segments] == ["A", "B"]


def test_http_errors_carry_status_code(audio):
    session = FakeSession([])
    session.post = lambda *a, **k: FakeResponse(503, {"error": "busy"})
    with pytest.raises(AssemblyAIError) as info:
        AssemblyAITranscriber(api_key="k", session=session).transcribe(str(audio))
    assert info.value.status_code == 503
