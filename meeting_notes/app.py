#!/usr/bin/env python3
"""Meeting Notes - Lazygit-inspired TUI redesign."""

import sys
import time
import subprocess
import os
import multiprocessing.resource_tracker
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.widgets import Static, Label, ListView, ListItem, Footer, Input, Button, TextArea
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from textual import work

from meeting_notes.recorder import AudioRecorder
from meeting_notes.transcriber import WhisperTranscriber
from meeting_notes.note_maker import NoteMaker
from meeting_notes.config import load_config, save_config, AppConfig, validate_config
from meeting_notes.settings import SettingsScreen
from meeting_notes.logger import setup_logging, get_logger

# Initialize logging
setup_logging(debug=False)
logger = get_logger(__name__)


class RecordingView(Container):
    """Full-screen view shown during active recording."""
    
    elapsed_time = reactive(0)  # seconds
    
    def compose(self) -> ComposeResult:
        """Build the recording view UI."""
        with Vertical(id="recording-container"):
            # Two-column layout: status on left, inputs on right
            with Horizontal(id="recording-columns"):
                # Left column: Recording status and monitoring info
                with Vertical(id="recording-left-column"):
                    # Status header
                    yield Static("🔴  RECORDING", id="recording-status")
                    
                    # Timer display
                    yield Static("00:00", id="recording-timer")
                    
                    # Audio device info
                    yield Static("", id="audio-device-info")
                
                # Right column: User input fields
                with Vertical(id="recording-right-column"):
                    # Optional title input
                    yield Static("Meeting Title (optional):", id="title-label")
                    yield Input(placeholder="Enter meeting title...", id="meeting-title-input")
                    
                    # User notes area
                    yield Static("Your Notes:", id="notes-label")
                    yield TextArea(id="user-notes-input", language="markdown")
            
            # Instruction hints at the bottom (full width)
            yield Static("Press 's' to stop and process recording", id="stop-hint")
            yield Static("Press 'x' to cancel and discard recording", id="cancel-hint")
            yield Static("Press 'Esc' to unfocus title input", id="esc-hint")
    
    def watch_elapsed_time(self, time: int) -> None:
        """Update timer display when elapsed_time changes."""
        minutes = time // 60
        seconds = time % 60
        timer = self.query_one("#recording-timer", Static)
        timer.update(f"{minutes:02d}:{seconds:02d}")
    
    def on_key(self, event) -> None:
        """Handle key events for the recording view."""
        if event.key == "escape":
            # Unfocus the title input or notes textarea so global key
            # bindings (like 's' to stop) work again without tabbing away.
            try:
                if self._has_focused_input():
                    self.screen.set_focus(None)
                    event.prevent_default()
            except Exception:
                pass  # Inputs not found or not mounted
        elif event.key == "s" and not self._has_focused_input():
            # Allow 's' to stop the recording even when the recording view
            # is focused but no input widget within it is. Without this,
            # the user has to manually tab away from inputs first.
            event.prevent_default()
            self.app.action_stop_recording()
        elif event.key == "x" and not self._has_focused_input():
            event.prevent_default()
            self.app.action_cancel_recording()

    def _has_focused_input(self) -> bool:
        """Check if any text input widget within this view has focus."""
        try:
            title_input = self.query_one("#meeting-title-input", Input)
            notes_input = self.query_one("#user-notes-input", TextArea)
            return title_input.has_focus or notes_input.has_focus
        except Exception:
            return False


class MeetingListItem(ListItem):
    """A single meeting in the list."""
    
    def __init__(self, note_path: Path):
        self.note_path = note_path
        
        # Parse note metadata
        try:
            with open(note_path, 'r') as f:
                content = f.read()
                
            date_line = [l for l in content.split('\n') if l.startswith('date:')]
            time_line = [l for l in content.split('\n') if l.startswith('time:')]
            title_line = [l for l in content.split('\n') if l.startswith('title:')]
            word_count_line = [l for l in content.split('\n') if l.startswith('word_count:')]
            tags_line = [l for l in content.split('\n') if l.startswith('tags:')]
            
            self.date = date_line[0].split(':', 1)[1].strip() if date_line else 'Unknown'
            self.time = time_line[0].split(':', 1)[1].strip().strip('"') if time_line else 'Unknown'
            title = title_line[0].split(':', 1)[1].strip().strip('"') if title_line else note_path.stem
            self.word_count = word_count_line[0].split(':', 1)[1].strip() if word_count_line else '0'
            
            # Parse tags from frontmatter (format: tags: [tag1, tag2])
            if tags_line:
                tags_str = tags_line[0].split(':', 1)[1].strip()
                tags_str = tags_str.strip('[]')
                self.tags = [t.strip() for t in tags_str.split(',') if t.strip() and t.strip() != 'meeting' and t.strip() != 'auto-generated']
            else:
                self.tags = []
            
            self.title = title[:40] + '...' if len(title) > 40 else title
            self.full_title = title  # Store full title for searching
            
        except Exception:
            self.date = 'Unknown'
            self.time = 'Unknown'
            self.title = note_path.stem
            self.full_title = note_path.stem
            self.word_count = '0'
            self.tags = []
        
        # Build label with tags if present
        tags_display = f" [{', '.join(self.tags)}]" if self.tags else ""
        label_text = f"{self.date} {self.time}\n{self.title}{tags_display}\n({self.word_count} words)"
        super().__init__(Label(label_text))
    
    def matches_search(self, query: str) -> bool:
        """Check if this meeting matches the search query."""
        if not query:
            return True
        
        query = query.lower()
        
        # Search in title, date, and tags
        return (
            query in self.full_title.lower() or
            query in self.date.lower() or
            query in self.time.lower() or
            any(query in tag.lower() for tag in self.tags)
        )


class NoteViewer(ScrollableContainer):
    """Display selected meeting note content."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_note = None
        
    def show_note(self, note_path: Path):
        """Display note content."""
        self.current_note = note_path
        
        try:
            with open(note_path, 'r') as f:
                content = f.read()
            
            # Remove frontmatter for cleaner display
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    content = parts[2].strip()
            
            # Strip out "## Full Transcript" section for backwards compatibility with old notes
            if '## Full Transcript' in content:
                content = content.split('## Full Transcript')[0].strip()
                content += "\n\n---\n\n*This is an old format note. The transcript has been hidden. Press 't' to view in a separate window.*"
            
            self.remove_children()
            self.mount(Static(content))
            
        except Exception as e:
            self.remove_children()
            self.mount(Static(f"[red]Error loading note:[/red] {e}"))
    
    def show_empty(self):
        """Show empty state."""
        self.remove_children()
        self.mount(Static("[dim]Select a meeting to view notes\n\nPress 'r' to start recording[/dim]"))


class ManageTagsScreen(ModalScreen[list]):
    """Modal screen for managing meeting tags."""
    
    CSS = """
    ManageTagsScreen {
        align: center middle;
    }
    
    #tags-dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    
    #tags-title {
        text-align: center;
        margin: 1 0;
        color: $text;
    }
    
    #current-tags {
        margin: 1 0;
        color: $text-muted;
    }
    
    #tags-input {
        width: 100%;
        margin: 1 0;
    }
    
    #tags-hint {
        color: $text-muted;
        text-align: center;
        margin: 0 0 1 0;
    }
    
    #tags-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    
    .tags-button {
        margin: 0 1;
    }
    """
    
    def __init__(self, current_tags: list, **kwargs):
        super().__init__(**kwargs)
        self.current_tags = current_tags or []
    
    def compose(self) -> ComposeResult:
        with Container(id="tags-dialog"):
            yield Static("🏷️  Manage Tags", id="tags-title")
            
            tags_display = ", ".join(self.current_tags) if self.current_tags else "No tags"
            yield Static(f"Current tags: {tags_display}", id="current-tags")
            
            yield Input(placeholder="Enter tags (comma-separated)...", id="tags-input")
            yield Static("Tip: Use commas to separate multiple tags", id="tags-hint")
            
            with Horizontal(id="tags-buttons"):
                yield Button("Cancel", variant="default", id="cancel-button", classes="tags-button")
                yield Button("Save", variant="primary", id="save-button", classes="tags-button")
    
    def on_mount(self) -> None:
        """Focus the input and populate with current tags."""
        tags_input = self.query_one("#tags-input", Input)
        if self.current_tags:
            tags_input.value = ", ".join(self.current_tags)
        tags_input.focus()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-button":
            tags_text = self.query_one("#tags-input", Input).value.strip()
            if tags_text:
                # Parse comma-separated tags
                tags = [t.strip() for t in tags_text.split(',') if t.strip()]
                self.dismiss(tags)
            else:
                self.dismiss([])
        else:
            self.dismiss(None)
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        tags_text = event.value.strip()
        if tags_text:
            tags = [t.strip() for t in tags_text.split(',') if t.strip()]
            self.dismiss(tags)
        else:
            self.dismiss([])


class TranscriptViewer(ModalScreen):
    """Modal screen for viewing full transcript."""
    
    CSS = """
    TranscriptViewer {
        align: center middle;
    }
    
    #transcript-container {
        width: 90%;
        height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 0;
    }
    
    #transcript-header {
        dock: top;
        width: 100%;
        height: 3;
        background: $primary;
        color: $text;
        content-align: center middle;
        text-style: bold;
        padding: 1 2;
    }
    
    #transcript-content {
        width: 100%;
        height: 1fr;
        border: none;
        padding: 2;
    }
    
    #transcript-path {
        dock: top;
        width: 100%;
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        content-align: left middle;
        padding: 0 2;
    }
    
    #transcript-footer {
        dock: bottom;
        width: 100%;
        height: 3;
        background: $surface-darken-1;
        color: $text-muted;
        content-align: center middle;
        padding: 1 2;
    }
    """
    
    def __init__(self, transcript_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.transcript_path = transcript_path
    
    def compose(self) -> ComposeResult:
        """Build the transcript viewer UI."""
        with Container(id="transcript-container"):
            yield Static(f"TRANSCRIPT: {self.transcript_path.stem}", id="transcript-header")
            yield Static(f"📄 {self.transcript_path.absolute()}", id="transcript-path")
            
            try:
                content = self.transcript_path.read_text()
                yield ScrollableContainer(Static(content), id="transcript-content")
            except Exception as e:
                yield Static(f"[red]Error loading transcript:[/red] {e}", id="transcript-content")
            
            yield Static("Press 'Esc' to close  |  Press 'e' to open in editor", id="transcript-footer")
    
    def on_key(self, event) -> None:
        """Handle key events."""
        if event.key == "escape":
            self.dismiss()
        elif event.key == "e":
            self.dismiss()
            # Trigger edit action on parent app
            self.app.action_edit_transcript(self.transcript_path)


class EditTitleScreen(ModalScreen[str]):
    """Modal screen for editing meeting title."""
    
    CSS = """
    EditTitleScreen {
        align: center middle;
    }
    
    #edit-dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    
    #edit-title-label {
        text-align: center;
        margin: 1 0;
        color: $text;
    }
    
    #edit-title-input {
        width: 100%;
        margin: 1 0;
    }
    
    #edit-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    
    .edit-button {
        margin: 0 1;
    }
    """
    
    def __init__(self, current_title: str, **kwargs):
        super().__init__(**kwargs)
        self.current_title = current_title
    
    def compose(self) -> ComposeResult:
        with Container(id="edit-dialog"):
            yield Static("✏️  Edit Meeting Title", id="edit-title-label")
            yield Input(value=self.current_title, placeholder="Enter new title...", id="edit-title-input")
            with Horizontal(id="edit-buttons"):
                yield Button("Cancel", variant="default", id="cancel-button", classes="edit-button")
                yield Button("Save", variant="primary", id="save-button", classes="edit-button")
    
    def on_mount(self) -> None:
        """Focus the input when mounted."""
        self.query_one("#edit-title-input", Input).focus()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-button":
            new_title = self.query_one("#edit-title-input", Input).value.strip()
            if new_title:
                self.dismiss(new_title)
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        new_title = event.value.strip()
        if new_title:
            self.dismiss(new_title)


class ConfirmDeleteScreen(ModalScreen):
    """Modal screen for confirming meeting deletion."""
    
    CSS = """
    ConfirmDeleteScreen {
        align: center middle;
    }
    
    #confirm-dialog {
        width: 60;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    
    #confirm-message {
        text-align: center;
        margin: 1 0;
        color: $text;
    }
    
    #confirm-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    
    .confirm-button {
        margin: 0 1;
    }
    """
    
    def __init__(self, meeting_title: str, **kwargs):
        super().__init__(**kwargs)
        self.meeting_title = meeting_title
    
    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            yield Static("⚠️  Delete Meeting?", id="confirm-title")
            yield Static(f'Are you sure you want to delete:\n"{self.meeting_title}"?\n\nThis cannot be undone.', id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", variant="primary", id="cancel-button", classes="confirm-button")
                yield Button("Delete", variant="error", id="delete-button", classes="confirm-button")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "delete-button":
            self.dismiss(True)
        else:
            self.dismiss(False)


class MeetingNotesApp(App):
    """Main application with Lazygit-inspired layout."""
    
    CSS = """
    Screen {
        layout: vertical;
    }
    
    #main-panels {
        layout: horizontal;
        height: 1fr;
    }
    
    #meetings-panel {
        width: 35%;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }
    
    #search-input {
        margin-bottom: 1;
        width: 100%;
    }
    
    #note-panel {
        width: 65%;
        height: 100%;
        border: solid $primary;
        padding: 1;
        margin-left: 1;
    }
    
    RecordingView {
        width: 100%;
        height: 100%;
        border: solid $error;
        padding: 2;
        background: $panel;
        align: center middle;
    }
    
    #recording-container {
        width: 90%;
        height: 90%;
        align: center middle;
    }
    
    #recording-columns {
        width: 100%;
        height: 1fr;
        layout: horizontal;
    }
    
    #recording-left-column {
        width: 40%;
        height: 100%;
        padding: 2;
        align: center top;
    }
    
    #recording-right-column {
        width: 60%;
        height: 100%;
        padding: 2;
    }
    
    #recording-status {
        text-align: center;
        text-style: bold;
        color: $error;
        margin: 2 0;
        content-align: center middle;
    }
    
    #recording-timer {
        text-align: center;
        text-style: bold;
        color: $text;
        height: 5;
        content-align: center middle;
        margin: 2 0;
    }
    
    #audio-device-info {
        text-align: center;
        color: $text-muted;
        margin: 2 0;
        padding: 1;
        background: $panel;
        border: solid $primary;
        width: 100%;
    }
    
    #title-label {
        color: $text-muted;
        margin-bottom: 1;
    }
    
    #meeting-title-input {
        width: 100%;
        margin: 0 0 2 0;
    }
    
    #notes-label {
        color: $text-muted;
        margin-bottom: 1;
    }
    
    #user-notes-input {
        width: 100%;
        height: 1fr;
    }
    
    #stop-hint, #cancel-hint, #esc-hint {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    
    .panel-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    
    ListView {
        height: 1fr;
        margin-top: 1;
    }
    
    ListItem {
        padding: 1 0;
    }
    
    ListItem:hover {
        background: $boost;
    }
    
    Footer {
        background: $panel;
    }
    """
    
    BINDINGS = [
        Binding("r", "start_recording", "Record", show=True),
        Binding("s", "stop_recording", "Stop", show=False, priority=True),
        Binding("x", "cancel_recording", "Cancel", show=False, priority=True),
        Binding("o", "open_in_editor", "Open", show=True),
        Binding("c", "copy_to_clipboard", "Copy", show=True),
        Binding("p", "copy_path", "Copy Path", show=True),
        Binding("f", "show_in_folder", "Show in Folder", show=True),
        Binding("d", "delete_meeting", "Delete", show=True),
        Binding("e", "edit_title", "Edit Title", show=True),
        Binding("t", "view_transcript", "Transcript", show=True),
        Binding("T", "manage_tags", "Tags", show=True),
        Binding("comma", "open_settings", "Settings", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]
    
    def __init__(self, dev_mode: bool = False):
        super().__init__()
        self.dev_mode = dev_mode
        
        # Load configuration
        self.config = load_config()
        
        # Validate config
        valid, error = validate_config(self.config)
        if not valid:
            print(f"Warning: Config validation failed: {error}")
            print("Using default values for invalid settings")
        
        # Initialize components with config values
        self.recorder: Optional[AudioRecorder] = None
        self.transcriber = WhisperTranscriber(self.config.whisper_model)
        
        # Get appropriate API key based on provider (check config first, then env vars)
        api_key = None
        if self.config.ai_provider == "openai":
            api_key = self.config.openai_api_key or os.getenv("OPENAI_API_KEY")
        elif self.config.ai_provider == "anthropic":
            api_key = self.config.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        elif self.config.ai_provider == "openrouter":
            api_key = self.config.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
        elif self.config.ai_provider == "copilot":
            api_key = self.config.github_copilot_token or os.getenv("GITHUB_COPILOT_TOKEN")
        
        self.note_maker = NoteMaker(
            output_dir=self.config.notes_dir,
            transcripts_dir=self.config.transcripts_dir,
            ai_provider=self.config.ai_provider,
            ai_model=self.config.ai_model,
            api_key=api_key
        )
        self.notes_dir = Path(self.config.notes_dir).expanduser()
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.is_recording = False
        self.timer_interval = None
        self.recording_start_time = None
        self.all_note_paths = []  # Store all note paths for filtering

        # Clean up old recordings on startup
        self._cleanup_old_recordings()

    def _cleanup_old_recordings(self) -> None:
        """Delete .wav recordings older than recording_retention_days.

        No-op if retention_days <= 0 or the recordings dir doesn't exist.
        Errors are logged but not raised — cleanup is best-effort.
        """
        retention_days = getattr(self.config, "recording_retention_days", 0)
        if retention_days <= 0:
            return
        recordings_dir = Path(self.config.recordings_dir).expanduser()
        if not recordings_dir.is_dir():
            return
        cutoff = datetime.now() - timedelta(days=retention_days)
        for wav_file in recordings_dir.glob("*.wav"):
            try:
                if datetime.fromtimestamp(wav_file.stat().st_mtime) < cutoff:
                    logger.info(
                        f"Removing old recording: {wav_file.name} "
                        f"(older than {retention_days} days)"
                    )
                    wav_file.unlink()
            except Exception as e:
                logger.warning(f"Failed to remove {wav_file.name}: {e}")

    def compose(self) -> ComposeResult:
        """Build the UI."""
        # Main content area
        with Container(id="main-panels"):
            # Meetings list panel
            with Vertical(id="meetings-panel"):
                yield Static("Meeting Notes", classes="panel-title")
                yield Input(placeholder="Search meetings...", id="search-input")
                yield ListView(id="meetings")
            
            # Note viewer panel  
            with Vertical(id="note-panel"):
                yield Static("Note Preview", classes="panel-title")
                yield NoteViewer(id="note-viewer")
        
        # Footer with keyboard shortcuts
        yield Footer()
    
    def on_mount(self) -> None:
        """Initialize app on mount."""
        logger.info("Initializing Meeting Notes app")
        logger.info(f"Config: {self.config.to_safe_dict()}")
        logger.debug(f"Dev mode: {self.dev_mode}")
        
        self.title = "Meeting Notes"
        self.sub_title = "Keyboard-driven meeting recorder"
        self.load_meetings()
        
        # Initialize recorder with config
        logger.info(f"Initializing audio recorder (mode: {self.config.recording_mode})")
        self.recorder = AudioRecorder(
            output_dir=self.config.recordings_dir,
            mode=self.config.recording_mode,
            dev_mode=self.dev_mode
        )
        
        # Clear status file on startup
        self._write_status_file("idle")
        
        # Show empty state
        viewer = self.query_one("#note-viewer", NoteViewer)
        viewer.show_empty()
        
        # Focus on the meetings list instead of search input
        try:
            meetings_list = self.query_one("#meetings", ListView)
            meetings_list.focus()
        except Exception as e:
            logger.warning(f"Could not focus on meetings list: {e}")
    
    def on_unmount(self) -> None:
        """Cleanup when app exits."""
        # Stop any active recording to clean up processes
        if self.recorder and self.recorder.is_recording():
            try:
                self.recorder.stop_recording()
            except Exception:
                pass  # Ignore errors during shutdown
        
        # Stop timer if running
        if self.timer_interval:
            try:
                self.timer_interval.stop()
            except Exception:
                pass
    
    def load_meetings(self):
        """Load meeting notes from disk."""
        notes = sorted(
            self.notes_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        # Store all note paths
        self.all_note_paths = list(notes)
        
        # Apply current search filter
        self.filter_meetings()
    
    def filter_meetings(self, query: str = ""):
        """Filter meetings based on search query."""
        try:
            meeting_list = self.query_one("#meetings", ListView)
        except Exception:
            return  # ListView not mounted yet
        
        meeting_list.clear()
        
        if not self.all_note_paths:
            meeting_list.append(ListItem(Label("[dim]No meetings yet\nPress 'r' to record[/dim]")))
            return
        
        # Filter meetings by query - create fresh MeetingListItem for each check
        filtered_paths = []
        for note_path in self.all_note_paths:
            # Create temporary item to check if it matches
            temp_item = MeetingListItem(note_path)
            if temp_item.matches_search(query):
                filtered_paths.append(note_path)
        
        if not filtered_paths:
            meeting_list.append(ListItem(Label(f"[dim]No meetings match '{query}'[/dim]")))
        else:
            # Create fresh MeetingListItem instances for display
            for note_path in filtered_paths:
                meeting_list.append(MeetingListItem(note_path))
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle meeting selection."""
        if isinstance(event.item, MeetingListItem):
            viewer = self.query_one("#note-viewer", NoteViewer)
            viewer.show_note(event.item.note_path)
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "search-input":
            self.filter_meetings(event.value)
    
    def _write_status_file(self, status: str, title: str = "", duration: str = "") -> None:
        """Write status file for Waybar integration.
        
        Args:
            status: One of "idle", "recording", "processing"
            title: Optional meeting title (for recording status)
            duration: Optional duration string like "05:42" (for recording status)
        """
        try:
            status_file = Path(__file__).parent.parent / ".status"
            with open(status_file, 'w') as f:
                f.write(f'STATUS="{status}"\n')
                if title:
                    f.write(f'TITLE="{title}"\n')
                if duration:
                    f.write(f'DURATION="{duration}"\n')
        except Exception as e:
            logger.warning(f"Failed to write status file: {e}")
    
    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Control which actions are available based on recording state."""
        if action == "start_recording":
            return not self.is_recording
        elif action in ["stop_recording", "cancel_recording"]:
            return self.is_recording
        return True  # All other actions always available
    
    def update_recording_timer(self) -> None:
        """Called every second to update recording timer."""
        if self.is_recording and self.recording_start_time:
            elapsed = int(time.time() - self.recording_start_time)
            duration_str = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
            
            # Update status file with current duration
            self._write_status_file("recording", duration=duration_str)
            
            try:
                recording_view = self.query_one(RecordingView)
                recording_view.elapsed_time = elapsed
            except Exception:
                pass  # View might not be mounted yet
    
    def action_start_recording(self) -> None:
        """Start recording and switch to full-screen recording view."""
        logger.info("Starting recording")
        if self.recorder and not self.recorder.is_recording():
            try:
                # Hide main panels
                main_panels = self.query_one("#main-panels", Container)
                main_panels.display = False
                
                # Mount recording view
                recording_view = RecordingView()
                self.mount(recording_view)
                
                # Start actual recording
                self.recorder.start_recording()
                self.is_recording = True
                self.recording_start_time = time.time()
                logger.info("Recording started successfully")
                
                # Update status file for Waybar
                self._write_status_file("recording", duration="00:00")
                
                # Get and display audio device info
                device_info = self.recorder.get_audio_device_info()
                mode_display = {
                    'mic': '🎤 Microphone Only',
                    'system': '🔊 System Audio Only',
                    'combined': '🎤🔊 Microphone + System Audio'
                }
                info_lines = [mode_display.get(device_info['mode'], device_info['mode'])]
                
                if 'mic_device' in device_info:
                    info_lines.append(f"Mic: {device_info['mic_device']}")
                if 'system_device' in device_info:
                    info_lines.append(f"System: {device_info['system_device']}")
                
                audio_info_text = '\n'.join(info_lines)
                audio_info_widget = recording_view.query_one("#audio-device-info", Static)
                audio_info_widget.update(audio_info_text)
                
                # Start timer updates (every 1 second)
                self.timer_interval = self.set_interval(1.0, self.update_recording_timer)
                
                # Update footer bindings
                self.refresh_bindings()
                
            except Exception as e:
                logger.error(f"Failed to start recording: {e}", exc_info=True)
                self.notify(f"Failed to start recording: {e}", severity="error")
                self.is_recording = False
                # Restore main panels if something failed
                try:
                    main_panels = self.query_one("#main-panels", Container)
                    main_panels.display = True
                except Exception:
                    pass
    
    def action_cancel_recording(self) -> None:
        """Cancel recording and discard without processing."""
        logger.info("Cancelling recording")
        if not self.is_recording or not self.recorder:
            return
        
        try:
            # Stop timer
            if self.timer_interval:
                self.timer_interval.stop()
                self.timer_interval = None
            
            # Stop and discard recording
            self.recorder.stop_recording()
            self.is_recording = False
            self.recording_start_time = None
            logger.info("Recording cancelled successfully")
            
            # Update status back to idle
            self._write_status_file("idle")
            
            # Remove recording view
            try:
                recording_view = self.query_one(RecordingView)
                recording_view.remove()
            except Exception:
                pass
            
            # Show main panels
            main_panels = self.query_one("#main-panels", Container)
            main_panels.display = True
            
            # Update footer bindings
            self.refresh_bindings()
            
            # Notify user
            self.notify("Recording cancelled", severity="warning")
            
        except Exception as e:
            logger.error(f"Failed to cancel recording: {e}", exc_info=True)
            self.notify(f"Failed to cancel recording: {e}", severity="error")
    
    def action_stop_recording(self) -> None:
        """Stop recording, get title if provided, and process."""
        logger.info("Stopping recording")
        if self.recorder and self.recorder.is_recording():
            try:
                # Get meeting title if provided
                meeting_title = None
                user_notes = ""
                try:
                    recording_view = self.query_one(RecordingView)
                    title_input = recording_view.query_one("#meeting-title-input", Input)
                    meeting_title = title_input.value.strip() if title_input.value else None
                    if meeting_title:
                        logger.info(f"Meeting title: {meeting_title}")
                    
                    # Get user notes from text area
                    notes_input = recording_view.query_one("#user-notes-input", TextArea)
                    user_notes = notes_input.text.strip() if notes_input.text else ""
                    if user_notes:
                        logger.info(f"User notes captured: {len(user_notes)} characters")
                except Exception:
                    pass  # No title input found
                
                # Stop timer
                if self.timer_interval:
                    self.timer_interval.stop()
                    self.timer_interval = None
                
                # Stop recording
                audio_path = self.recorder.stop_recording()
                self.is_recording = False
                self.recording_start_time = None
                logger.info(f"Recording stopped. Audio saved to: {audio_path}")
                
                # Update status to processing
                self._write_status_file("processing")
                
                # Remove recording view
                try:
                    recording_view = self.query_one(RecordingView)
                    recording_view.remove()
                except Exception:
                    pass
                
                # Show main panels
                main_panels = self.query_one("#main-panels", Container)
                main_panels.display = True
                
                # Update footer bindings
                self.refresh_bindings()
                
                # Process in background
                self.notify("Processing recording...", severity="information")
                self.process_recording(audio_path, meeting_title, user_notes)
                
            except Exception as e:
                logger.error(f"Failed to stop recording: {e}", exc_info=True)
                self.notify(f"Failed to stop recording: {e}", severity="error")
                self.is_recording = False
    
    @work(exclusive=True, thread=True)
    def process_recording(self, audio_path: str, meeting_title: Optional[str] = None, user_notes: str = "") -> None:
        """Process recording in background thread."""
        logger.info(f"Processing recording: {audio_path}")
        try:
            # Load Whisper model (if not already loaded)
            logger.info("Loading Whisper model")
            self.call_from_thread(self.notify, f"Loading Whisper {self.config.whisper_model} model...", severity="information")
            self.transcriber.load_model()
            
            # Transcribe
            logger.info("Starting transcription")
            self.call_from_thread(self.notify, "Transcribing audio (this may take a few minutes)...", severity="information")
            result = self.transcriber.transcribe(audio_path)
            
            word_count = len(result.text.split())
            logger.info(f"Transcription complete: {word_count} words")
            self.call_from_thread(self.notify, f"✓ Transcribed {word_count} words. Generating AI summary...", severity="information")
            
            # Format transcript
            formatted = '\n\n'.join([
                f'**[{int(seg.start // 60):02d}:{int(seg.start % 60):02d}]** {seg.text.strip()}'
                for seg in result.segments
            ])
            
            # Generate note with AI summary (pass custom title if provided)
            logger.info("Creating note with AI summary")
            duration = result.segments[-1].end if result.segments else 0
            note_path, transcript_path, ai_error = self.note_maker.create_note(
                transcript_text=result.text,
                formatted_transcript=formatted,
                duration=duration,
                title=meeting_title,
                user_notes=user_notes
            )
            
            # Update UI
            if ai_error:
                logger.warning(f"Note created but AI summarization failed: {ai_error}")
                self.call_from_thread(self.notify, f"⚠ Note created but {ai_error}", severity="warning")
                self.call_from_thread(self.notify, f"Check ~/.config/meeting-notes/errors.log for details", severity="warning")
            else:
                logger.info(f"Note created successfully: {note_path}")
                logger.info(f"Transcript saved: {transcript_path}")
                self.call_from_thread(self.notify, f"✓ Note created: {Path(note_path).name}", severity="information")
            self.call_from_thread(self.load_meetings)
            
            # Clear status back to idle after successful processing
            self._write_status_file("idle")
            
        except Exception as e:
            logger.error(f"Error processing recording: {e}", exc_info=True)
            self.call_from_thread(self.notify, f"Error processing: {e}", severity="error")
            
            # Clear status back to idle after error
            self._write_status_file("idle")
    
    def _open_in_new_terminal(self, editor: str, file_path: str) -> bool:
        """
        Open editor in a new terminal window.
        
        Returns:
            True if successfully opened in new terminal, False otherwise
        """
        import shutil
        
        # If running inside tmux, open editor in a new tmux window
        if os.getenv("TMUX"):
            try:
                subprocess.Popen(["tmux", "new-window", "--", editor, file_path])
                return True
            except Exception:
                pass  # Fall through to terminal detection
        # Try to detect terminal emulator (check $TERMINAL first, then common terminals)
        terminal = os.getenv('TERMINAL')
        
        terminal_commands = {
            'alacritty': ['alacritty', '-e', editor, file_path],
            'kitty': ['kitty', editor, file_path],
            'ghostty': ['ghostty', '-e', editor, file_path],
            'wezterm': ['wezterm', 'start', '--', editor, file_path],
            'foot': ['foot', editor, file_path],
            'gnome-terminal': ['gnome-terminal', '--', editor, file_path],
            'konsole': ['konsole', '-e', editor, file_path],
            'xterm': ['xterm', '-e', editor, file_path],
            'urxvt': ['urxvt', '-e', editor, file_path],
            'st': ['st', '-e', editor, file_path],
        }
        
        # If $TERMINAL is set and exists, try it first
        if terminal:
            terminal_name = Path(terminal).name
            if terminal_name in terminal_commands:
                try:
                    subprocess.Popen(terminal_commands[terminal_name])
                    return True
                except Exception:
                    pass  # Fall through to auto-detection
        
        # Auto-detect by checking which terminals are available
        for term_name, cmd in terminal_commands.items():
            if shutil.which(term_name):
                try:
                    subprocess.Popen(cmd)
                    return True
                except Exception:
                    continue
        
        return False
    
    def action_open_in_editor(self) -> None:
        """Open selected note in editor in a new terminal window."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            import shutil
            
            editor = self.config.editor
            file_path = str(viewer.current_note)
            
            # Check if editor exists
            if not shutil.which(editor):
                self.notify(f"✗ Editor '{editor}' not found. Update in settings (,) or install it.", severity="error")
                return
            
            # Try to open in new terminal window
            try:
                if self._open_in_new_terminal(editor, file_path):
                    self.notify(f"✓ Opened in {editor}", severity="information")
                else:
                    # Fallback: open in same terminal (will replace TUI temporarily)
                    subprocess.Popen([editor, file_path])
                    self.notify(f"⚠ Opened in {editor} (same terminal - no terminal emulator detected)", severity="warning")
            except Exception as e:
                self.notify(f"✗ Failed to open editor: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_copy_to_clipboard(self) -> None:
        """Copy selected note to clipboard."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            try:
                with open(viewer.current_note, 'r') as f:
                    content = f.read()
                
                # Try clipboard tools in order: wl-copy (Wayland), xclip, xsel
                import shutil
                
                if shutil.which('wl-copy'):
                    # Wayland (Hyprland, Sway, etc.)
                    process = subprocess.Popen(
                        ['wl-copy'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(content.encode())
                    self.notify("✓ Copied to clipboard", severity="information")
                elif shutil.which('xclip'):
                    # X11 with xclip
                    process = subprocess.Popen(
                        ['xclip', '-selection', 'clipboard'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(content.encode())
                    self.notify("✓ Copied to clipboard", severity="information")
                elif shutil.which('xsel'):
                    # X11 with xsel
                    process = subprocess.Popen(
                        ['xsel', '--clipboard'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(content.encode())
                    self.notify("✓ Copied to clipboard", severity="information")
                else:
                    self.notify("Install wl-clipboard (Wayland) or xclip/xsel (X11)", severity="error")
                    
            except Exception as e:
                self.notify(f"Failed to copy: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_show_in_folder(self) -> None:
        """Show selected note in file manager and focus on the file."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            try:
                import shutil
                file_path = str(viewer.current_note.absolute())
                folder = str(viewer.current_note.parent)

                # If a terminal file browser is configured, use it
                terminal_browser = self.config.terminal_file_browser
                if terminal_browser and shutil.which(terminal_browser):
                    if self._open_in_new_terminal(terminal_browser, folder):
                        self.notify(
                            f"Opened in {terminal_browser}", severity="information"
                        )
                        return

                # Try to detect file manager and use --select flag
                # This focuses on the specific file instead of just opening the folder
                file_managers = [
                    (['dolphin', '--select', file_path], 'dolphin'),  # KDE
                    (['nautilus', '--select', file_path], 'nautilus'),  # GNOME
                    (['nemo', file_path], 'nemo'),  # Cinnamon
                    (['thunar', file_path], 'thunar'),  # XFCE
                    (['pcmanfm', '--select', file_path], 'pcmanfm'),  # LXDE
                ]
                
                # Try each file manager
                opened = False
                for cmd, fm_name in file_managers:
                    if shutil.which(cmd[0]):
                        subprocess.Popen(cmd)
                        self.notify(f"Opened in {fm_name}", severity="information")
                        return

                # Fallback: try to auto-detect a terminal file browser
                terminal_browsers = [
                    "ranger",
                    "yazi",
                    "lf",
                    "nnn",
                    "vifm",
                    "mc",
                    "vidir",
                    "joshuto",
                    "broot",
                ]
                for browser in terminal_browsers:
                    if shutil.which(browser):
                        if self._open_in_new_terminal(browser, folder):
                            self.notify(f"Opened in {browser}", severity="information")
                            return
                
                # Fallback: just open the folder
                subprocess.Popen(['xdg-open', folder])
                self.notify(f"Opened folder (file manager doesn't support --select)", severity="information")

            except Exception as e:
                self.notify(f"Failed to open: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_copy_path(self) -> None:
        """Copy the full absolute path of the selected note to clipboard."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            try:
                import shutil
                file_path = str(viewer.current_note.absolute())
                
                # Try clipboard tools in order: wl-copy (Wayland), xclip, xsel
                if shutil.which('wl-copy'):
                    # Wayland (Hyprland, Sway, etc.)
                    process = subprocess.Popen(
                        ['wl-copy'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(file_path.encode())
                    self.notify(f"✓ Copied path to clipboard", severity="information")
                elif shutil.which('xclip'):
                    # X11 with xclip
                    process = subprocess.Popen(
                        ['xclip', '-selection', 'clipboard'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(file_path.encode())
                    self.notify(f"✓ Copied path to clipboard", severity="information")
                elif shutil.which('xsel'):
                    # X11 with xsel
                    process = subprocess.Popen(
                        ['xsel', '--clipboard'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(file_path.encode())
                    self.notify(f"✓ Copied path to clipboard", severity="information")
                else:
                    self.notify("Install wl-clipboard (Wayland) or xclip/xsel (X11)", severity="error")
                    
            except Exception as e:
                self.notify(f"Failed to copy path: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_delete_meeting(self) -> None:
        """Delete the selected meeting after confirmation."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            # Get the meeting item to show its title
            meeting_item = None
            try:
                meeting_list = self.query_one("#meetings", ListView)
                if meeting_list.highlighted_child and isinstance(meeting_list.highlighted_child, MeetingListItem):
                    meeting_item = meeting_list.highlighted_child
            except Exception:
                pass
            
            title = meeting_item.full_title if meeting_item else viewer.current_note.name
            
            # Show confirmation modal
            self.push_screen(
                ConfirmDeleteScreen(title),
                self.handle_delete_confirmation
            )
        else:
            self.notify("No note selected", severity="warning")
    
    def handle_delete_confirmation(self, confirmed: Optional[bool]) -> None:
        """Handle the result of delete confirmation."""
        if confirmed is True:
            viewer = self.query_one("#note-viewer", NoteViewer)
            if viewer.current_note:
                try:
                    # Delete the file
                    os.remove(viewer.current_note)
                    self.notify(f"✓ Deleted meeting", severity="information")
                    
                    # Clear viewer
                    viewer.show_empty()
                    
                    # Reload meetings list
                    self.load_meetings()
                    
                except Exception as e:
                    self.notify(f"Failed to delete: {e}", severity="error")
    
    def action_edit_title(self) -> None:
        """Edit the title of the selected meeting."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            # Get the current title
            meeting_item = None
            try:
                meeting_list = self.query_one("#meetings", ListView)
                if meeting_list.highlighted_child and isinstance(meeting_list.highlighted_child, MeetingListItem):
                    meeting_item = meeting_list.highlighted_child
            except Exception:
                pass
            
            current_title = meeting_item.full_title if meeting_item else "Meeting"
            
            # Show edit modal
            self.push_screen(
                EditTitleScreen(current_title),
                self.handle_edit_title
            )
        else:
            self.notify("No note selected", severity="warning")
    
    def handle_edit_title(self, new_title: Optional[str]) -> None:
        """Handle the result of title editing."""
        if new_title:
            viewer = self.query_one("#note-viewer", NoteViewer)
            if viewer.current_note:
                try:
                    # Read the file
                    with open(viewer.current_note, 'r') as f:
                        content = f.read()
                    
                    # Update the title in frontmatter
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            frontmatter = parts[1]
                            body = parts[2]
                            
                            # Replace title line
                            lines = frontmatter.split('\n')
                            new_lines = []
                            for line in lines:
                                if line.strip().startswith('title:'):
                                    new_lines.append(f'title: "{new_title}"')
                                else:
                                    new_lines.append(line)
                            
                            new_frontmatter = '\n'.join(new_lines)
                            new_content = f"---{new_frontmatter}---{body}"
                            
                            # Write back to file
                            with open(viewer.current_note, 'w') as f:
                                f.write(new_content)
                            
                            self.notify(f"✓ Updated title", severity="information")
                            
                            # Reload meetings and refresh viewer
                            self.load_meetings()
                            viewer.show_note(viewer.current_note)
                    
                except Exception as e:
                    self.notify(f"Failed to update title: {e}", severity="error")
    
    def action_manage_tags(self) -> None:
        """Manage tags for the selected meeting."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            # Get the current tags
            meeting_item = None
            try:
                meeting_list = self.query_one("#meetings", ListView)
                if meeting_list.highlighted_child and isinstance(meeting_list.highlighted_child, MeetingListItem):
                    meeting_item = meeting_list.highlighted_child
            except Exception:
                pass
            
            current_tags = meeting_item.tags if meeting_item else []
            
            # Show tags modal
            self.push_screen(
                ManageTagsScreen(current_tags),
                self.handle_manage_tags
            )
        else:
            self.notify("No note selected", severity="warning")
    
    def handle_manage_tags(self, new_tags: Optional[list]) -> None:
        """Handle the result of tag management."""
        if new_tags is not None:
            viewer = self.query_one("#note-viewer", NoteViewer)
            if viewer.current_note:
                try:
                    # Read the file
                    with open(viewer.current_note, 'r') as f:
                        content = f.read()
                    
                    # Update the tags in frontmatter
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            frontmatter = parts[1]
                            body = parts[2]
                            
                            # Build new tags list (always include default tags)
                            all_tags = ['meeting', 'auto-generated'] + new_tags
                            tags_str = f"tags: [{', '.join(all_tags)}]"
                            
                            # Replace tags line
                            lines = frontmatter.split('\n')
                            new_lines = []
                            tags_found = False
                            for line in lines:
                                if line.strip().startswith('tags:'):
                                    new_lines.append(tags_str)
                                    tags_found = True
                                else:
                                    new_lines.append(line)
                            
                            # If no tags line exists, add it before the closing ---
                            if not tags_found:
                                new_lines.insert(-1, tags_str)
                            
                            new_frontmatter = '\n'.join(new_lines)
                            new_content = f"---{new_frontmatter}---{body}"
                            
                            # Write back to file
                            with open(viewer.current_note, 'w') as f:
                                f.write(new_content)
                            
                            tag_count = len(new_tags)
                            self.notify(f"✓ Updated tags ({tag_count} custom tag{'s' if tag_count != 1 else ''})", severity="information")
                            
                            # Reload meetings and refresh viewer
                            self.load_meetings()
                            viewer.show_note(viewer.current_note)
                    
                except Exception as e:
                    self.notify(f"Failed to update tags: {e}", severity="error")
    
    def action_view_transcript(self) -> None:
        """View transcript for the selected meeting."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            # Guard against the underlying note file having been deleted
            # since it was loaded (e.g. cleaned up externally) — otherwise
            # the open() below crashes with FileNotFoundError.
            if not Path(viewer.current_note).exists():
                self.notify("Note file no longer exists", severity="warning")
                return
            try:
                # Read note to get transcript_file from frontmatter
                with open(viewer.current_note, 'r') as f:
                    content = f.read()
                
                # Parse transcript_file from frontmatter
                transcript_filename = None
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 2:
                        frontmatter = parts[1]
                        for line in frontmatter.split('\n'):
                            if line.strip().startswith('transcript_file:'):
                                transcript_filename = line.split(':', 1)[1].strip().strip('"')
                                break
                
                if transcript_filename:
                    transcript_path = Path(self.config.transcripts_dir).expanduser() / transcript_filename
                    
                    if transcript_path.exists():
                        self.push_screen(TranscriptViewer(transcript_path))
                    else:
                        self.notify(f"Transcript not found: {transcript_filename}", severity="error")
                else:
                    self.notify("This note doesn't have a separate transcript file", severity="warning")
                    
            except Exception as e:
                logger.error(f"Error viewing transcript: {e}", exc_info=True)
                self.notify(f"Error viewing transcript: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_edit_transcript(self, transcript_path: Path) -> None:
        """Open transcript in external editor."""
        editor = self.config.editor or os.environ.get('EDITOR', 'vim')
        
        try:
            # Suspend the app to open editor
            with self.suspend():
                subprocess.run([editor, str(transcript_path)])
            
            self.notify(f"Edited: {transcript_path.name}")
        except Exception as e:
            logger.error(f"Error opening editor: {e}", exc_info=True)
            self.notify(f"Error opening editor: {e}", severity="error")
    
    def action_open_settings(self) -> None:
        """Open the settings screen."""
        self.push_screen(SettingsScreen(self.config), self.handle_settings_closed)
    
    def handle_settings_closed(self, new_config: Optional[AppConfig]) -> None:
        """Handle settings screen closing."""
        if new_config:
            # Settings were saved, reload config and components
            self.config = new_config
            
            # Reinitialize components with new config
            self.transcriber = WhisperTranscriber(self.config.whisper_model)
            
            # Get appropriate API key based on provider (check config first, then env vars)
            api_key = None
            if self.config.ai_provider == "openai":
                api_key = self.config.openai_api_key or os.getenv("OPENAI_API_KEY")
            elif self.config.ai_provider == "anthropic":
                api_key = self.config.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
            elif self.config.ai_provider == "openrouter":
                api_key = self.config.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
            elif self.config.ai_provider == "copilot":
                api_key = self.config.github_copilot_token or os.getenv("GITHUB_COPILOT_TOKEN")
            
            self.note_maker = NoteMaker(
                output_dir=self.config.notes_dir,
                transcripts_dir=self.config.transcripts_dir,
                ai_provider=self.config.ai_provider,
                ai_model=self.config.ai_model,
                api_key=api_key
            )
            self.notes_dir = Path(self.config.notes_dir).expanduser()
            self.notes_dir.mkdir(parents=True, exist_ok=True)
            
            # Reinitialize recorder if not currently recording
            if not self.is_recording:
                self.recorder = AudioRecorder(
                    output_dir=self.config.recordings_dir,
                    mode=self.config.recording_mode,
                    dev_mode=self.dev_mode
                )
            
            # Reload meetings from potentially new directory
            self.load_meetings()
            
            self.notify("✓ Settings saved and applied", severity="information")


def run(dev_mode: bool = False):
    """Run the application."""
    # Pre-initialize the multiprocessing resource tracker while sys.stderr
    # is still the real fd 2.  Textual's app.run() redirects stderr to a
    # _PrintCapture whose fileno() returns -1, which later causes
    # "bad value(s) in fds_to_keep" when whisper/tqdm triggers
    # resource_tracker._launch().
    try:
        multiprocessing.resource_tracker.ensure_running()
    except Exception:
        pass  # Non-critical, best effort

    # Belt-and-braces: tqdm lazily creates a multiprocessing.RLock the first
    # time it is used, which on Python 3.14 also triggers the same
    # fork_exec/fds_to_keep validation against a now-closed stderr. Force
    # tqdm's lock to be created here while stderr is still valid; tqdm caches
    # it at the class level so whisper's later progress bars reuse it.
    try:
        import tqdm
        tqdm.tqdm.get_lock()
    except Exception:
        pass  # Non-critical, best effort

    app = MeetingNotesApp(dev_mode=dev_mode)
    app.run()
