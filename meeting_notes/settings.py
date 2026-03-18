"""Settings UI screens for Meeting Notes."""

from pathlib import Path
from typing import Optional
import subprocess
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.widgets import Static, Label, Button, Input, Select, ListView, ListItem
from textual.screen import Screen, ModalScreen
from textual.reactive import reactive
from textual import work

from meeting_notes.config import AppConfig, save_config, validate_config, get_config_path
from meeting_notes.ollama_utils import (
    get_installed_models,
    get_recommended_models,
    install_model,
    check_ollama_installed
)


class InstallingModelScreen(ModalScreen):
    """Screen shown while installing an Ollama model."""
    
    CSS = """
    InstallingModelScreen {
        align: center middle;
    }
    
    #installing-dialog {
        width: 70;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 2;
    }
    
    #installing-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    
    #installing-status {
        text-align: center;
        color: $text;
        margin: 1 0;
    }
    
    #installing-progress {
        text-align: center;
        color: $text-muted;
        margin: 1 0;
    }
    
    #installing-spinner {
        text-align: center;
        color: $accent;
        margin: 1 0;
    }
    """
    
    status_message = reactive("Starting...")
    progress_percentage = reactive(0)
    
    def __init__(self, model_name: str, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_index = 0
    
    def compose(self) -> ComposeResult:
        with Container(id="installing-dialog"):
            yield Static(f"Installing {self.model_name}", id="installing-title")
            yield Static("", id="installing-status")
            yield Static("", id="installing-progress")
            yield Static("", id="installing-spinner")
    
    def on_mount(self) -> None:
        """Start the installation and spinner animation."""
        self.update_spinner()
        self.start_installation()
    
    def watch_status_message(self, message: str) -> None:
        """Update status message when changed."""
        self.query_one("#installing-status", Static).update(message)
    
    def watch_progress_percentage(self, percentage: int) -> None:
        """Update progress when changed."""
        if percentage > 0:
            bar_width = 40
            filled = int(bar_width * percentage / 100)
            bar = "█" * filled + "░" * (bar_width - filled)
            self.query_one("#installing-progress", Static).update(f"{bar} {percentage}%")
    
    def update_spinner(self) -> None:
        """Update spinner animation."""
        spinner = self.spinner_frames[self.spinner_index]
        self.query_one("#installing-spinner", Static).update(f"{spinner} Please wait...")
        self.spinner_index = (self.spinner_index + 1) % len(self.spinner_frames)
        self.set_timer(0.1, self.update_spinner)
    
    @work(exclusive=True, thread=True)
    def start_installation(self) -> None:
        """Install the model in a background thread."""
        try:
            def progress_callback(status: str, percentage: int):
                self.call_from_thread(setattr, self, "status_message", status)
                self.call_from_thread(setattr, self, "progress_percentage", percentage)
            
            success = install_model(self.model_name, progress_callback)
            
            if success:
                self.call_from_thread(self.dismiss, True)
            else:
                self.call_from_thread(self.dismiss, False)
        
        except Exception as e:
            error_msg = str(e)
            self.call_from_thread(self.dismiss, False)
            # TODO: Show error to user


class InstallModelScreen(ModalScreen[str]):
    """Modal for selecting and installing a new Ollama model."""
    
    CSS = """
    InstallModelScreen {
        align: center middle;
    }
    
    #install-dialog {
        width: 80;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 2;
    }
    
    #install-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    
    #install-list {
        height: 15;
        margin: 1 0;
    }
    
    #install-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    
    .install-button {
        margin: 0 1;
    }
    
    ListItem {
        padding: 1;
    }
    
    ListItem:hover {
        background: $boost;
    }
    """
    
    def __init__(self, installed_models: list, **kwargs):
        super().__init__(**kwargs)
        self.installed_models = [m.name for m in installed_models]
        self.selected_model = None
    
    def compose(self) -> ComposeResult:
        with Container(id="install-dialog"):
            yield Static("📦 Install Ollama Model", id="install-title")
            yield Static("Select a model to install:", id="install-subtitle")
            
            with ListView(id="install-list"):
                for model_info in get_recommended_models():
                    name = model_info["name"]
                    desc = model_info["description"]
                    size = model_info["size"]
                    is_recommended = model_info["recommended"]
                    is_installed = name in self.installed_models
                    
                    star = "⭐" if is_recommended else "  "
                    installed_mark = " ✓ (installed)" if is_installed else ""
                    label_text = f"{star} {name} - {desc} ({size}){installed_mark}"
                    
                    item = ListItem(Label(label_text))
                    item.model_name = name  # Store model name
                    item.is_installed = is_installed
                    yield item
            
            with Horizontal(id="install-buttons"):
                yield Button("Cancel", variant="default", id="cancel-button", classes="install-button")
                yield Button("Install", variant="primary", id="install-button", classes="install-button")
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle model selection."""
        if hasattr(event.item, 'model_name'):
            self.selected_model = event.item.model_name
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "install-button":
            if self.selected_model:
                # Check if already installed
                list_view = self.query_one("#install-list", ListView)
                if list_view.highlighted_child and hasattr(list_view.highlighted_child, 'is_installed'):
                    if list_view.highlighted_child.is_installed:
                        self.app.notify("Model is already installed", severity="warning")
                        return
                
                self.dismiss(self.selected_model)
            else:
                self.app.notify("Please select a model first", severity="warning")
        else:
            self.dismiss(None)


class CopilotAuthScreen(ModalScreen):
    """Modal screen for GitHub Copilot authentication via Device Flow."""

    CSS = """
    CopilotAuthScreen {
        align: center middle;
    }
    
    #copilot-auth-dialog {
        width: 70;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 2;
    }
    
    #copilot-auth-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    
    #copilot-auth-instructions {
        text-align: center;
        color: $text;
        margin: 1 0;
    }
    
    #copilot-auth-code {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin: 1 0;
        padding: 1;
        border: solid $primary;
    }
    
    #copilot-auth-url {
        text-align: center;
        color: $text;
        margin: 1 0;
    }
    
    #copilot-auth-status {
        text-align: center;
        color: $text-muted;
        margin: 1 0;
    }
    
    #copilot-auth-spinner {
        text-align: center;
        color: $accent;
        margin: 1 0;
    }
    
    #copilot-auth-cancel {
        width: 100%;
        margin-top: 1;
    }
    """

    status_message = reactive("Starting authentication...")

    def __init__(self, client_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self.spinner_frames = ["|", "/", "-", "\\"]
        self.spinner_index = 0
        self._user_code = ""
        self._verification_uri = ""
        self._client_id = client_id

    def compose(self) -> ComposeResult:
        with Container(id="copilot-auth-dialog"):
            yield Static("GitHub Copilot Authentication", id="copilot-auth-title")
            yield Static("", id="copilot-auth-instructions")
            yield Static("", id="copilot-auth-code")
            yield Static("", id="copilot-auth-url")
            yield Static("", id="copilot-auth-status")
            yield Static("", id="copilot-auth-spinner")
            yield Button("Cancel", variant="default", id="copilot-auth-cancel")

    def on_mount(self) -> None:
        """Start the device flow on mount."""
        self.update_spinner()
        self.start_auth()

    def watch_status_message(self, message: str) -> None:
        """Update status display."""
        try:
            self.query_one("#copilot-auth-status", Static).update(message)
        except Exception:
            pass

    def update_spinner(self) -> None:
        """Animate the spinner while waiting."""
        spinner = self.spinner_frames[self.spinner_index]
        try:
            self.query_one("#copilot-auth-spinner", Static).update(
                f"{spinner} Waiting for authorization..."
            )
        except Exception:
            pass
        self.spinner_index = (self.spinner_index + 1) % len(self.spinner_frames)
        self.set_timer(0.3, self.update_spinner)

    @work(exclusive=True, thread=True)
    def start_auth(self) -> None:
        """Run the device flow in a background thread."""
        try:
            from meeting_notes.copilot_auth import (
                start_device_flow,
                poll_for_token,
                DeviceFlowError,
            )

            # Step 1: Start device flow
            self.app.call_from_thread(
                setattr, self, "status_message", "Requesting device code..."
            )
            flow = start_device_flow(client_id=self._client_id or None)

            user_code = flow["user_code"]
            verification_uri = flow["verification_uri"]
            device_code = flow["device_code"]
            interval = flow.get("interval", 5)

            # Step 2: Show the code to the user
            def show_code():
                try:
                    self.query_one("#copilot-auth-instructions", Static).update(
                        "Enter this code in your browser:"
                    )
                    self.query_one("#copilot-auth-code", Static).update(
                        f"  {user_code}  "
                    )
                    self.query_one("#copilot-auth-url", Static).update(
                        f"{verification_uri}"
                    )
                except Exception:
                    pass

            self.app.call_from_thread(show_code)
            self.app.call_from_thread(
                setattr, self, "status_message", "Waiting for you to authorize..."
            )

            # Step 3: Poll for token
            access_token = poll_for_token(device_code=device_code, interval=interval, client_id=self._client_id or None)

            # Success
            self.app.call_from_thread(self.dismiss, access_token)

        except DeviceFlowError as e:
            self.app.call_from_thread(setattr, self, "status_message", f"Error: {e}")
            import time

            time.sleep(3)
            self.app.call_from_thread(self.dismiss, None)

        except Exception as e:
            self.app.call_from_thread(
                setattr, self, "status_message", f"Unexpected error: {e}"
            )
            import time

            time.sleep(3)
            self.app.call_from_thread(self.dismiss, None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "copilot-auth-cancel":
            self.dismiss(None)


class SettingsScreen(Screen):
    """Full-screen settings interface."""
    
    CSS = """
    SettingsScreen {
        background: $surface;
    }
    
    #settings-container {
        width: 100%;
        height: 100%;
        layout: horizontal;
    }
    
    #settings-sidebar {
        width: 25%;
        height: 100%;
        border-right: solid $primary;
        padding: 1;
    }
    
    #settings-content-wrapper {
        width: 75%;
        height: 100%;
        layout: vertical;
    }
    
    #settings-content {
        width: 100%;
        height: 1fr;
        padding: 2;
        overflow-y: auto;
    }
    
    #settings-footer {
        width: 100%;
        height: 5;
        padding: 1 2;
        background: $surface;
        border-top: solid $primary;
    }
    
    .sidebar-item {
        padding: 1;
        margin-bottom: 1;
    }
    
    .sidebar-item:hover {
        background: $boost;
    }
    
    .sidebar-item.-active {
        background: $accent;
        color: $text;
    }
    
    .settings-section-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        margin-top: 2;
    }
    
    .settings-field {
        margin-bottom: 2;
    }
    
    .settings-label {
        color: $text-muted;
        margin-bottom: 1;
    }
    
    .settings-input {
        width: 100%;
    }
    
    .settings-hint {
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
    }
    
    #model-list {
        margin: 1 0;
        max-height: 10;
    }
    
    #settings-buttons {
        width: 100%;
        align: center middle;
    }
    
    .settings-action-button {
        margin: 0 1;
    }
    """
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("v", "view_config_file", "View Config File"),
    ]
    
    def __init__(self, config: AppConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config.to_dict()  # Work with a copy
        self.original_config = config
        self.current_section = "ai"
    
    def compose(self) -> ComposeResult:
        with Container(id="settings-container"):
            # Sidebar
            with Vertical(id="settings-sidebar"):
                yield Static("⚙️  Settings", classes="settings-section-title")
                yield Button("AI Models", id="section-ai", classes="sidebar-item -active")
                yield Button("Directories", id="section-dirs", classes="sidebar-item")
                yield Button("Audio", id="section-audio", classes="sidebar-item")
                yield Button("Editor", id="section-editor", classes="sidebar-item")
            
            # Content area wrapper (scrollable content + fixed footer)
            with Vertical(id="settings-content-wrapper"):
                # Scrollable content
                with ScrollableContainer(id="settings-content"):
                    yield from self.render_ai_section()
                
                # Fixed footer with action buttons
                with Container(id="settings-footer"):
                    with Horizontal(id="settings-buttons"):
                        yield Button("Cancel", variant="default", id="cancel-button", classes="settings-action-button")
                        yield Button("Save", variant="primary", id="save-button", classes="settings-action-button")
    
    def render_ai_section(self) -> list:
        """Render AI Models section."""
        widgets = []
        
        widgets.append(Static("🤖 AI Summarization", classes="settings-section-title"))
        
        # AI Provider Selection
        widgets.append(Static("AI Provider", classes="settings-label"))
        
        current_provider = self.config.get("ai_provider", "none")
        
        providers = [
            ("openai", "OpenAI (GPT-4o Mini/4o)", "Fast, cheap, great quality"),
            ("anthropic", "Anthropic (Claude)", "Excellent quality, best for action items"),
            ("openrouter", "OpenRouter", "Access to 300+ models"),
            ("copilot", "GitHub Copilot", "Included with Copilot subscription"),
            ("local", "Local (Ollama)", "Private, offline, slow"),
            ("none", "No AI", "Just transcripts, no summary"),
        ]
        
        for provider_id, provider_name, provider_desc in providers:
            is_current = provider_id == current_provider
            marker = "●" if is_current else "○"
            label = f"{marker} {provider_name}"
            btn = Button(label, id=f"provider-{provider_id}", variant="primary" if is_current else "default")
            btn.provider_id = provider_id
            widgets.append(btn)
            if is_current:
                widgets.append(Static(f"  → {provider_desc}", classes="settings-hint"))
        
        widgets.append(Static(""))  # Spacer
        
        # Show provider-specific settings
        if current_provider == "openai":
            widgets.extend(self.render_openai_settings())
        elif current_provider == "anthropic":
            widgets.extend(self.render_anthropic_settings())
        elif current_provider == "openrouter":
            widgets.extend(self.render_openrouter_settings())
        elif current_provider == "copilot":
            widgets.extend(self.render_copilot_settings())
        elif current_provider == "local":
            widgets.extend(self.render_local_ollama_settings())
        elif current_provider == "none":
            widgets.append(Static("✓ No AI summarization - transcripts only", classes="settings-hint"))
        
        # Whisper Model (Transcription)
        widgets.append(Static(""))  # Spacer
        widgets.append(Static("Whisper Model (Transcription)", classes="settings-label"))
        widgets.append(Static(f"Current: {self.config.get('whisper_model', 'base')}", classes="settings-hint"))
        widgets.append(Static("(Model selection coming soon)", classes="settings-hint"))
        
        return widgets
    
    def render_openai_settings(self) -> list:
        """Render OpenAI-specific settings."""
        widgets = []
        
        widgets.append(Static("OpenAI Settings", classes="settings-section-title"))
        
        # Model selection
        widgets.append(Static("Model", classes="settings-label"))
        current_model = self.config.get("ai_model", "mini")
        
        models = [
            ("mini", "GPT-4o Mini", "~$0.001/meeting - Ultra cheap"),
            ("standard", "GPT-4o", "~$0.015/meeting - Best quality"),
        ]
        
        for model_id, model_name, model_desc in models:
            is_current = model_id == current_model
            marker = "●" if is_current else "○"
            btn = Button(f"{marker} {model_name}", id=f"aimodel-{model_id}", 
                        variant="primary" if is_current else "default")
            btn.model_id = model_id
            widgets.append(btn)
            if is_current:
                widgets.append(Static(f"  → {model_desc}", classes="settings-hint"))
        
        # API Key
        widgets.append(Static("API Key", classes="settings-label"))
        api_key = self.config.get("openai_api_key", "")
        key_input = Input(value=api_key, password=True, id="openai-key-input", classes="settings-input",
                         placeholder="sk-... (or set OPENAI_API_KEY env var)")
        widgets.append(key_input)
        widgets.append(Static("💡 Tip: Use environment variable for security", classes="settings-hint"))
        
        return widgets
    
    def render_anthropic_settings(self) -> list:
        """Render Anthropic-specific settings."""
        widgets = []
        
        widgets.append(Static("Anthropic Claude Settings", classes="settings-section-title"))
        
        # Model selection
        widgets.append(Static("Model", classes="settings-label"))
        current_model = self.config.get("ai_model", "haiku")
        
        models = [
            ("haiku", "Claude Haiku 4.5", "~$0.005/meeting - Fast & affordable ⭐"),
            ("sonnet", "Claude Sonnet 4.6", "~$0.020/meeting - Best quality"),
        ]
        
        for model_id, model_name, model_desc in models:
            is_current = model_id == current_model
            marker = "●" if is_current else "○"
            btn = Button(f"{marker} {model_name}", id=f"aimodel-{model_id}", 
                        variant="primary" if is_current else "default")
            btn.model_id = model_id
            widgets.append(btn)
            if is_current:
                widgets.append(Static(f"  → {model_desc}", classes="settings-hint"))
        
        # API Key
        widgets.append(Static("API Key", classes="settings-label"))
        api_key = self.config.get("anthropic_api_key", "")
        key_input = Input(value=api_key, password=True, id="anthropic-key-input", classes="settings-input",
                         placeholder="sk-ant-... (or set ANTHROPIC_API_KEY env var)")
        widgets.append(key_input)
        widgets.append(Static("💡 Tip: Use environment variable for security", classes="settings-hint"))
        
        return widgets
    
    def render_openrouter_settings(self) -> list:
        """Render OpenRouter-specific settings."""
        widgets = []
        
        widgets.append(Static("OpenRouter Settings", classes="settings-section-title"))
        
        # Model selection
        widgets.append(Static("Model Tier", classes="settings-label"))
        current_model = self.config.get("ai_model", "balanced")
        
        models = [
            ("cheap", "Cheap (Gemini Flash)", "~$0.001/meeting"),
            ("balanced", "Balanced (Claude Haiku)", "~$0.01/meeting ⭐"),
            ("premium", "Premium (Claude Sonnet)", "~$0.03/meeting"),
        ]
        
        for model_id, model_name, model_desc in models:
            is_current = model_id == current_model
            marker = "●" if is_current else "○"
            btn = Button(f"{marker} {model_name}", id=f"aimodel-{model_id}", 
                        variant="primary" if is_current else "default")
            btn.model_id = model_id
            widgets.append(btn)
            if is_current:
                widgets.append(Static(f"  → {model_desc}", classes="settings-hint"))
        
        # API Key
        widgets.append(Static("API Key", classes="settings-label"))
        api_key = self.config.get("openrouter_api_key", "")
        key_input = Input(value=api_key, password=True, id="openrouter-key-input", classes="settings-input",
                         placeholder="sk-or-... (or set OPENROUTER_API_KEY env var)")
        widgets.append(key_input)
        widgets.append(Static("Get your key at: https://openrouter.ai/keys", classes="settings-hint"))
        
        return widgets
    
    def render_copilot_settings(self) -> list:
        """Render GitHub Copilot-specific settings."""
        widgets = []

        widgets.append(
            Static("GitHub Copilot Settings", classes="settings-section-title")
        )

        # Client ID input
        widgets.append(Static("OAuth App Client ID", classes="settings-label"))
        client_id = self.config.get("github_copilot_client_id", "")
        client_id_input = Input(
            value=client_id,
            id="copilot-client-id-input",
            classes="settings-input",
            placeholder="Ov23li... (or set GITHUB_COPILOT_CLIENT_ID env var)",
        )
        widgets.append(client_id_input)
        widgets.append(Static("Register at: https://github.com/settings/applications/new", classes="settings-hint"))

        # Token input (direct entry)
        widgets.append(Static("GitHub Token", classes="settings-label"))
        token = self.config.get("github_copilot_token", "")
        token_input = Input(
            value=token,
            password=True,
            id="copilot-token-input",
            classes="settings-input",
            placeholder="ghp_... or gho_... (or set GITHUB_COPILOT_TOKEN env var)",
        )
        widgets.append(token_input)

        # Auth status hint
        has_token = bool(token)
        if has_token:
            widgets.append(Static("Status: Authenticated", classes="settings-hint"))
        else:
            widgets.append(Static("Status: Not authenticated", classes="settings-hint"))

        # Device flow button as alternative
        auth_label = (
            "Re-authenticate with GitHub"
            if has_token
            else "Authenticate with GitHub (Device Flow)"
        )
        widgets.append(
            Button(
                auth_label,
                variant="default" if has_token else "warning",
                id="copilot-auth-button",
            )
        )
        widgets.append(
            Static(
                "Requires an active GitHub Copilot subscription",
                classes="settings-hint",
            )
        )

        widgets.append(Static(""))  # Spacer

        # Model selection
        widgets.append(Static("Model", classes="settings-label"))
        current_model = self.config.get("ai_model", "mini")

        models = [
            ("mini", "GPT-4o Mini", "Fast, lightweight"),
            ("standard", "GPT-4o", "Best quality"),
        ]

        for model_id, model_name, model_desc in models:
            is_current = model_id == current_model
            marker = "●" if is_current else "○"
            btn = Button(
                f"{marker} {model_name}",
                id=f"aimodel-{model_id}",
                variant="primary" if is_current else "default",
            )
            btn.model_id = model_id
            widgets.append(btn)
            if is_current:
                widgets.append(Static(f"  → {model_desc}", classes="settings-hint"))

        widgets.append(
            Static(
                "No per-request cost - included in your Copilot subscription",
                classes="settings-hint",
            )
        )

        return widgets

    def render_local_ollama_settings(self) -> list:
        """Render local Ollama settings."""
        widgets = []
        
        widgets.append(Static("Local Ollama Settings", classes="settings-section-title"))
        widgets.append(Static("⚠️  Warning: Very slow (10+ min per meeting)", classes="settings-hint"))
        widgets.append(Static("⚠️  High CPU usage (400%), not recommended", classes="settings-hint"))
        
        widgets.append(Static("Ollama Model", classes="settings-label"))
        
        try:
            installed = get_installed_models()
            if not installed:
                widgets.append(Static("⚠️  No Ollama models installed!", classes="settings-hint"))
                widgets.append(Button("Install a Model", variant="warning", id="install-model-button"))
            else:
                # Show installed models with current selection
                # `or` fallback handles empty-string config values, which
                # dict.get's default does not.
                current = self.config.get("ollama_model") or "llama3.2:3b"
                
                for model in installed:
                    is_current = model.name == current
                    marker = "●" if is_current else "○"
                    label = f"{marker} {model.name}"
                    if model.size:
                        label += f" ({model.size})"
                    
                    # Sanitize model name for ID (replace invalid chars with hyphens)
                    safe_id = model.name.replace(":", "-").replace(".", "-")
                    btn = Button(label, id=f"model-{safe_id}", variant="primary" if is_current else "default")
                    btn.model_name = model.name
                    widgets.append(btn)
                
                widgets.append(Button("+ Install New Model", variant="default", id="install-model-button"))
        
        except Exception as e:
            widgets.append(Static(f"⚠️  Error loading models: {e}", classes="settings-hint"))
        
        return widgets
    
    def render_directories_section(self) -> list:
        """Render Directories section."""
        widgets = []
        
        widgets.append(Static("📁 Directories", classes="settings-section-title"))
        
        widgets.append(Static("Notes Directory", classes="settings-label"))
        notes_input = Input(value=self.config["notes_dir"], id="notes-dir-input", classes="settings-input")
        widgets.append(notes_input)
        widgets.append(Static("• Relative path (e.g., 'notes') or absolute path (e.g., '/home/user/notes')", classes="settings-hint"))
        widgets.append(Static("• Directory must already exist", classes="settings-hint"))
        widgets.append(Static(f"• Current resolves to: {Path(self.config['notes_dir']).expanduser().absolute()}", classes="settings-hint"))
        
        widgets.append(Static("Recordings Directory", classes="settings-label"))
        rec_input = Input(value=self.config["recordings_dir"], id="rec-dir-input", classes="settings-input")
        widgets.append(rec_input)
        widgets.append(Static("• Relative path (e.g., 'recordings') or absolute path", classes="settings-hint"))
        widgets.append(Static("• Directory must already exist", classes="settings-hint"))
        widgets.append(Static(f"• Current resolves to: {Path(self.config['recordings_dir']).expanduser().absolute()}", classes="settings-hint"))
        
        widgets.append(Static("Transcripts Directory", classes="settings-label"))
        trans_input = Input(value=self.config["transcripts_dir"], id="trans-dir-input", classes="settings-input")
        widgets.append(trans_input)
        widgets.append(Static("• Relative path (e.g., 'transcripts') or absolute path", classes="settings-hint"))
        widgets.append(Static("• Directory must already exist", classes="settings-hint"))
        widgets.append(Static(f"• Current resolves to: {Path(self.config['transcripts_dir']).expanduser().absolute()}", classes="settings-hint"))
        
        return widgets
    
    def render_audio_section(self) -> list:
        """Render Audio section."""
        widgets = []
        
        widgets.append(Static("🎤 Audio Settings", classes="settings-section-title"))
        
        widgets.append(Static("Recording Mode", classes="settings-label"))
        # TODO: Add proper Select widget once implemented
        widgets.append(Static(f"Current: {self.config['recording_mode']}", classes="settings-hint"))
        widgets.append(Static("(Mode selection coming soon)", classes="settings-hint"))
        
        return widgets
    
    def render_editor_section(self) -> list:
        """Render Editor section."""
        widgets = []
        
        widgets.append(Static("✏️  Editor", classes="settings-section-title"))
        
        widgets.append(Static("Preferred Editor", classes="settings-label"))
        editor_input = Input(value=self.config["editor"], id="editor-input", classes="settings-input")
        widgets.append(editor_input)
        widgets.append(Static("Command used to open notes (e.g. nvim, code, emacs)", classes="settings-hint"))
        
        
        widgets.append(Static("Terminal File Browser", classes="settings-label"))
        browser_input = Input(value=self.config.get("terminal_file_browser", ""), id="terminal-file-browser-input", classes="settings-input")
        widgets.append(browser_input)
        widgets.append(Static("Terminal file browser for browsing notes (e.g. ranger, vidir, nnn, lf, vifm, yazi)", classes="settings-hint"))
        return widgets
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        
        # Section navigation
        if button_id and button_id.startswith("section-"):
            section = button_id.split("-")[1]
            await self.switch_section(section)
        
        # Provider selection
        elif button_id and button_id.startswith("provider-"):
            if hasattr(event.button, 'provider_id'):
                self.config["ai_provider"] = event.button.provider_id
                # Set default model for provider
                if event.button.provider_id == "openai":
                    self.config["ai_model"] = "mini"
                elif event.button.provider_id == "anthropic":
                    self.config["ai_model"] = "haiku"
                elif event.button.provider_id == "openrouter":
                    self.config["ai_model"] = "balanced"
                elif event.button.provider_id == "copilot":
                    self.config["ai_model"] = "mini"
                elif event.button.provider_id == "local":
                    # `or` fallback so an empty-string ollama_model still
                    # produces a runnable default (dict.get only fills in the
                    # default when the key is missing entirely).
                    self.config["ai_model"] = self.config.get("ollama_model") or "llama3.2:3b"
                await self.refresh_content()
        
        # AI model selection (for cloud providers)
        elif button_id and button_id.startswith("aimodel-"):
            if hasattr(event.button, 'model_id'):
                self.config["ai_model"] = event.button.model_id
                await self.refresh_content()
        
        # Ollama model selection (for local provider)
        elif button_id and button_id.startswith("model-"):
            if hasattr(event.button, 'model_name'):
                self.config["ollama_model"] = event.button.model_name
                self.config["ai_model"] = event.button.model_name  # Sync ai_model
                await self.refresh_content()
        
        # Install model
        elif button_id == "install-model-button":
            self.action_install_model()
        
        # Copilot authentication
        elif button_id == "copilot-auth-button":
            self.action_copilot_auth()

        # Save/Cancel
        elif button_id == "save-button":
            self.action_save()
        elif button_id == "cancel-button":
            self.action_cancel()
    
    async def switch_section(self, section: str) -> None:
        """Switch to a different settings section."""
        self.current_section = section
        
        # Update sidebar highlights
        for item in self.query(".sidebar-item"):
            if item.id == f"section-{section}":
                item.add_class("-active")
            else:
                item.remove_class("-active")
        
        await self.refresh_content()
    
    async def refresh_content(self) -> None:
        """Refresh the content area based on current section."""
        content = self.query_one("#settings-content", ScrollableContainer)
        await content.remove_children()
        
        # Render appropriate section
        if self.current_section == "ai":
            widgets = self.render_ai_section()
        elif self.current_section == "dirs":
            widgets = self.render_directories_section()
        elif self.current_section == "audio":
            widgets = self.render_audio_section()
        elif self.current_section == "editor":
            widgets = self.render_editor_section()
        else:
            widgets = []
        
        # Mount all widgets (buttons are now in fixed footer, not here)
        for widget in widgets:
            await content.mount(widget)
    
    def action_install_model(self) -> None:
        """Open the install model dialog."""
        try:
            installed = get_installed_models()
            self.app.push_screen(InstallModelScreen(installed), self.handle_install_model)
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
    
    def handle_install_model(self, model_name: Optional[str]) -> None:
        """Handle model installation."""
        if model_name:
            # Show installing screen
            self.app.push_screen(InstallingModelScreen(model_name), self.handle_installation_complete)
    
    async def handle_installation_complete(self, success: bool) -> None:
        """Handle completion of model installation."""
        if success:
            self.app.notify("✓ Model installed successfully!", severity="information")
            # Refresh the content to show new model
            await self.refresh_content()
        else:
            self.app.notify("✗ Model installation failed", severity="error")
    
    def action_copilot_auth(self) -> None:
        """Start the GitHub Copilot device flow authentication."""
        self.app.push_screen(CopilotAuthScreen(client_id=self.config.get("github_copilot_client_id", "")), self.handle_copilot_auth)

    async def handle_copilot_auth(self, access_token: Optional[str]) -> None:
        """Handle completion of Copilot authentication."""
        if access_token:
            self.config["github_copilot_token"] = access_token
            self.app.notify(
                "GitHub Copilot authenticated successfully!", severity="information"
            )
            await self.refresh_content()
        else:
            self.app.notify(
                "Copilot authentication cancelled or failed", severity="warning"
            )

    def action_save(self) -> None:
        """Save settings and close."""
        # Update config from inputs (only if they're currently mounted)
        try:
            notes_input = self.query("#notes-dir-input")
            if notes_input:
                self.config["notes_dir"] = notes_input[0].value.strip()
        except Exception:
            pass
        
        try:
            rec_input = self.query("#rec-dir-input")
            if rec_input:
                self.config["recordings_dir"] = rec_input[0].value.strip()
        except Exception:
            pass
        
        try:
            trans_input = self.query("#trans-dir-input")
            if trans_input:
                self.config["transcripts_dir"] = trans_input[0].value.strip()
        except Exception:
            pass
        
        try:
            editor_input = self.query("#editor-input")
            if editor_input:
                self.config["editor"] = editor_input[0].value.strip()
        except Exception:
            pass
        
        try:
            browser_input = self.query("#terminal-file-browser-input")
            if browser_input:
                self.config["terminal_file_browser"] = browser_input[0].value.strip()
        except Exception:
            pass
        
        # Update API keys from inputs
        try:
            openai_key = self.query("#openai-key-input")
            if openai_key:
                self.config["openai_api_key"] = openai_key[0].value.strip()
        except Exception:
            pass
        
        try:
            anthropic_key = self.query("#anthropic-key-input")
            if anthropic_key:
                self.config["anthropic_api_key"] = anthropic_key[0].value.strip()
        except Exception:
            pass
        
        try:
            openrouter_key = self.query("#openrouter-key-input")
            if openrouter_key:
                self.config["openrouter_api_key"] = openrouter_key[0].value.strip()
        except Exception:
            pass
        
        try:
            copilot_token = self.query("#copilot-token-input")
            if copilot_token:
                self.config["github_copilot_token"] = copilot_token[0].value.strip()
        except Exception:
            pass

        try:
            copilot_client_id = self.query("#copilot-client-id-input")
            if copilot_client_id:
                self.config["github_copilot_client_id"] = copilot_client_id[0].value.strip()
        except Exception:
            pass

        # Create config object and validate
        new_config = AppConfig.from_dict(self.config)
        valid, error = validate_config(new_config)
        
        if not valid:
            self.app.notify(f"✗ {error}", severity="error", timeout=10)
            return
        
        # Save to file
        try:
            save_config(new_config)
            self.dismiss(new_config)
        except Exception as e:
            self.app.notify(f"✗ Failed to save: {e}", severity="error")
    
    def action_cancel(self) -> None:
        """Cancel and close without saving."""
        self.dismiss(None)
    
    def action_view_config_file(self) -> None:
        """Open the config file in the configured editor."""
        config_path = get_config_path()
        editor = self.config.get("editor", "nvim")
        
        try:
            # Open in editor
            subprocess.Popen([editor, str(config_path)])
            self.app.notify(f"Opening config in {editor}: {config_path}", severity="information")
        except Exception as e:
            self.app.notify(f"Failed to open config: {e}", severity="error")
