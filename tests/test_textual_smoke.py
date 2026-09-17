"""Headless Textual smoke tests using App.run_test().

These are intentionally minimal — full UI flows are slow and brittle.
We just want to catch:
  - The app actually starts without raising
  - The settings screen opens
  - Switching providers in settings doesn't crash with the duplicate-ID
    error (the bug PR #9 fixed; this is a regression guard)

Whisper is imported lazily by the transcriber, so these UI tests remain
lightweight and run in CI without torch. To run locally:

    pip install -e ".[all,dev]"
    pytest tests/test_textual_smoke.py
"""
import pytest

# Skip cleanly for contributors who only installed non-UI test dependencies.
pytest.importorskip("textual", reason="run `pip install -e .[all,dev]` to enable Textual smoke tests")

from omascribe.app import OmascribeApp, NoteViewer, RecordingView  # noqa: E402  (deliberate import-after-skip)
from omascribe.settings import SettingsScreen  # noqa: E402
from textual.widgets import Input, ListView  # noqa: E402


@pytest.mark.asyncio
async def test_app_starts_and_exits_cleanly(tmp_path, monkeypatch):
    """The app should mount cleanly in headless mode and respond to ctrl+c-equivalent."""
    # Sandbox config & data dirs so the test doesn't touch real ones
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = OmascribeApp()
    async with app.run_test() as pilot:
        # Just let the app stabilise. If anything raises during mount,
        # we'd see it here.
        await pilot.pause()
        assert app.is_running
        # Quit cleanly
        app.exit()


@pytest.mark.asyncio
async def test_settings_screen_opens(tmp_path, monkeypatch):
    """Pressing ',' should open the settings screen without error."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = OmascribeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(",")
        await pilot.pause()
        # SettingsScreen should now be on the screen stack.
        # (We don't import it for an isinstance check — its exact import
        # path isn't load-bearing; just confirm the stack changed.)
        assert len(app.screen_stack) >= 2, "settings screen should have been pushed"
        app.exit()


@pytest.mark.asyncio
async def test_switching_providers_does_not_duplicate_widget_ids(tmp_path, monkeypatch):
    """Regression test for issue #11 / PR #9.

    Switching AI providers used to crash with `DuplicateIds: provider-openai`
    because remove_children() wasn't awaited before mount(). This test
    rapidly clicks between providers and asserts no exception.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = OmascribeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(",")  # open settings
        await pilot.pause()

        # Click each provider button in turn.  If remove_children isn't
        # awaited, the second mount of any provider button will raise
        # DuplicateIds.
        provider_ids = ["provider-openai", "provider-anthropic",
                        "provider-openrouter", "provider-anthropic"]
        for pid in provider_ids:
            try:
                await pilot.click(f"#{pid}")
                await pilot.pause()
            except Exception as e:
                # Surface DuplicateIds clearly if it ever comes back
                if "Duplicate" in type(e).__name__ or "already exists" in str(e):
                    pytest.fail(f"PR #9 regressed — DuplicateIds when clicking {pid}: {e}")
                # Other failures (e.g. button not found because layout
                # changed) shouldn't fail this specific regression test
                # — re-raise to fail loudly so the test gets updated.
                raise

        app.exit()


@pytest.mark.asyncio
async def test_compact_layout_and_settings_draft_survive_navigation(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = OmascribeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.has_class("compact")

        await pilot.press("2")
        await pilot.pause()
        assert app.query_one("#note-viewer", NoteViewer).has_focus
        await pilot.press("1")
        await pilot.pause()
        assert app.query_one("#meetings", ListView).has_focus

        await pilot.press(",")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        assert screen.has_class("compact")

        await pilot.press("3")
        await pilot.pause()
        assert screen.current_section == "audio"
        await pilot.press("1")
        await pilot.pause()
        assert screen.current_section == "ai"

        await pilot.click("#section-dirs")
        await pilot.pause()
        notes_input = screen.query_one("#notes-dir-input", Input)
        notes_input.value = str(tmp_path / "new-notes")
        await pilot.pause()
        await pilot.click("#section-ai")
        await pilot.pause()

        assert screen.config["notes_dir"] == str(tmp_path / "new-notes")
        app.exit()


@pytest.mark.asyncio
async def test_stop_failure_restores_library_view(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    class FailingRecorder:
        last_temp_files = [tmp_path / "temp-mic.wav"]

        def is_recording(self):
            return False

        def stop_recording(self):
            raise RuntimeError("mix failed")

    app = OmascribeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.recorder = FailingRecorder()
        app.is_recording = True
        app.recording_start_time = 1.0
        app.query_one("#main-panels").display = False
        await app.mount(RecordingView())
        await pilot.pause()

        app.action_stop_recording()
        await pilot.pause()

        assert not app.is_recording
        assert app.recording_start_time is None
        assert app.query_one("#main-panels").display
        assert not app.query(RecordingView)
        app.exit()


@pytest.mark.asyncio
async def test_import_recording_with_empty_dir_notifies(tmp_path, monkeypatch):
    """action_import_recording should not open the modal when there are no
    audio files — it should notify and no-op. Guards @vVasile29's #14 port."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = OmascribeApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        notifications = []
        original_notify = app.notify
        app.notify = lambda msg, **kw: notifications.append((msg, kw))
        try:
            app.action_import_recording()
            await pilot.pause()
        finally:
            app.notify = original_notify

        assert len(app.screen_stack) == 1, "modal should not open when recordings dir is empty"
        assert any("No audio files" in msg for msg, _ in notifications), notifications
        app.exit()


@pytest.mark.asyncio
async def test_import_recording_opens_picker_and_hands_file_to_pipeline(tmp_path, monkeypatch):
    """When files exist, the picker mounts, Enter selects the newest file,
    and it flows into process_recording (which we stub so we don't actually
    load Whisper / call cloud APIs)."""
    from pathlib import Path
    import time as _time
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    # Two files, different mtimes; newest should be selected first.
    older = recordings_dir / "older.wav"
    older.write_bytes(b"RIFF")
    _time.sleep(0.01)
    newer = recordings_dir / "newer.wav"
    newer.write_bytes(b"RIFF")

    app = OmascribeApp()
    app.config.recordings_dir = str(recordings_dir)

    handoffs = []
    app.process_recording = lambda path, meeting_title=None, user_notes="": handoffs.append(path)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_import_recording()
        await pilot.pause()
        assert len(app.screen_stack) == 2, "import picker should be pushed"

        await pilot.press("enter")
        await pilot.pause()

        assert handoffs == [str(newer)], f"expected newest-first selection, got {handoffs}"
        app.exit()


@pytest.mark.asyncio
async def test_import_recording_disabled_while_processing(tmp_path, monkeypatch):
    """check_action should hide the import binding once a pipeline is running,
    the same way it hides start_recording."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = OmascribeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.check_action("import_recording", ()) is True
        app.is_processing = True
        assert app.check_action("import_recording", ()) is False
        app.is_processing = False
        app.is_recording = True
        assert app.check_action("import_recording", ()) is False
        app.exit()


@pytest.mark.asyncio
async def test_assemblyai_provider_and_transcriber_switching(tmp_path, monkeypatch):
    """The AssemblyAI key input is shared by the summariser and transcriber
    sections; whichever combination is selected, it must mount exactly once."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = OmascribeApp()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        await pilot.press(",")
        await pilot.pause()
        screen = app.screen
        for button in ["provider-assemblyai", "transcriber-assemblyai", "provider-anthropic",
                       "transcriber-whisper", "transcriber-assemblyai", "provider-deepinfra",
                       "aimodel-opus", "provider-assemblyai"]:
            screen.query_one(f"#{button}").press()
            await pilot.pause()
            assert len(screen.query("#assemblyai-key-input")) <= 1
        assert screen.config["ai_provider"] == "assemblyai"
        assert screen.config["transcriber"] == "assemblyai"
        assert screen.config["ai_model"] == "sonnet"
        app.exit()

