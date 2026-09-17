"""Configuration management for Omascribe."""

import os
import tempfile
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class AppConfig:
    """Application configuration."""
    # AI Summarization
    ai_provider: str = "none"  # "openai", "anthropic", "openrouter", "assemblyai", "deepinfra", "local", or "none"
    ai_model: str = "haiku"  # Model tier (varies by provider)
    
    # API Keys (or set environment variables)
    openai_api_key: str = ""  # OPENAI_API_KEY
    anthropic_api_key: str = ""  # ANTHROPIC_API_KEY
    openrouter_api_key: str = ""  # OPENROUTER_API_KEY
    assemblyai_api_key: str = ""  # ASSEMBLYAI_API_KEY (transcription and LLM Gateway)
    deepinfra_api_key: str = ""  # DEEPINFRA_API_KEY
    
    # Legacy (kept for backwards compatibility)
    ollama_model: str = "llama3.2:3b"
    
    # Other settings
    # Transcription backend: "whisper" (local, needs the whisper extra) or
    # "assemblyai" (cloud, with speaker labels).
    transcriber: str = "whisper"
    whisper_model: str = "base"
    # Whisper compute device: "cpu" (default, safe everywhere), "cuda" (force GPU),
    # or "auto" (let whisper/torch decide). "cpu" matches the README's
    # privacy-first CPU pipeline and dodges broken-CUDA-wheel crashes like
    # "no kernel image is available for execution on the device".
    whisper_device: str = "cpu"
    notes_dir: str = "notes"
    recordings_dir: str = "recordings"
    transcripts_dir: str = "transcripts"
    editor: str = "nvim"
    terminal_file_browser: str = ""  # Terminal file browser (ranger, vidir, nnn, lf, vifm, yazi, etc.)
    recording_mode: str = "combined"
    # Per-device pinning. Empty string = use system default. Names should
    # match `pactl list sources/sinks short` output (e.g.
    # "alsa_input.pci-0000_00_1f.3.analog-stereo").
    mic_device: str = ""
    system_device: str = ""  # Output sink whose monitor we record from
    recording_retention_days: int = 0  # Retained for config compatibility; cleanup is now explicit only
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return asdict(self)
    
    def _redact_key(self, key: str) -> str:
        """Redact API key for logging."""
        return "[redacted]" if key else ""
    
    def to_safe_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary with redacted API keys (safe for logging)."""
        data = self.to_dict()
        # Redact sensitive keys
        if data.get('openai_api_key'):
            data['openai_api_key'] = self._redact_key(data['openai_api_key'])
        if data.get('anthropic_api_key'):
            data['anthropic_api_key'] = self._redact_key(data['anthropic_api_key'])
        if data.get('openrouter_api_key'):
            data['openrouter_api_key'] = self._redact_key(data['openrouter_api_key'])
        if data.get('assemblyai_api_key'):
            data['assemblyai_api_key'] = self._redact_key(data['assemblyai_api_key'])
        if data.get('deepinfra_api_key'):
            data['deepinfra_api_key'] = self._redact_key(data['deepinfra_api_key'])
        return data
    
    def provider_api_key(self) -> Optional[str]:
        """API key for the configured AI provider: config first, then env."""
        env_vars = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "assemblyai": "ASSEMBLYAI_API_KEY",
            "deepinfra": "DEEPINFRA_API_KEY",
        }
        env_var = env_vars.get(self.ai_provider)
        if not env_var:
            return None
        return getattr(self, f"{self.ai_provider}_api_key") or os.getenv(env_var)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AppConfig':
        """Create config from dictionary."""
        # Filter out any unknown keys
        valid_keys = {field for field in cls.__dataclass_fields__}
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered_data)


def get_config_path() -> Path:
    """Get the path to the config file."""
    # Use XDG_CONFIG_HOME if set, otherwise ~/.config
    config_home = os.environ.get('XDG_CONFIG_HOME')
    if config_home:
        config_dir = Path(config_home) / "omascribe"
    else:
        config_dir = Path.home() / ".config" / "omascribe"
    
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config_dir, 0o700)
    return config_dir / "config.yaml"


def load_config() -> AppConfig:
    """Load configuration from file, or create default if not exists."""
    config_path = get_config_path()
    logger.info(f"Loading config from: {config_path}")
    
    if not config_path.exists():
        # First run - create default config
        logger.info("Config file not found, creating default config")
        config = AppConfig()
        save_config(config)
        return config
    
    try:
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
        
        if data is None:
            # Empty file
            logger.warning("Config file is empty, using defaults")
            return AppConfig()
        
        config = AppConfig.from_dict(data)
        logger.info(f"Config loaded successfully (ai_provider: {config.ai_provider}, ai_model: {config.ai_model})")
        return config
    
    except Exception as e:
        logger.error(f"Could not load config from {config_path}: {e}", exc_info=True)
        print(f"Warning: Could not load config from {config_path}: {e}")
        print("Using default configuration")
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """Save configuration to file."""
    config_path = get_config_path()
    logger.info(f"Saving config to: {config_path}")
    
    try:
        fd, temporary = tempfile.mkstemp(dir=config_path.parent, prefix=".config-", suffix=".yaml")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as f:
                yaml.safe_dump(config.to_dict(), f, default_flow_style=False, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, config_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        
        logger.info("Config saved successfully with secure permissions (600)")
    except Exception as e:
        logger.error(f"Failed to save config: {e}", exc_info=True)
        raise RuntimeError(f"Failed to save config: {e}")


def validate_config(config: AppConfig) -> tuple[bool, Optional[str]]:
    """
    Validate configuration values.
    
    Returns:
        (is_valid, error_message)
    """
    string_fields = (
        "ai_provider", "ai_model", "ollama_model", "transcriber", "whisper_model", "whisper_device",
        "notes_dir", "recordings_dir", "transcripts_dir", "editor", "terminal_file_browser",
        "recording_mode", "mic_device", "system_device",
    )
    for field in string_fields:
        if not isinstance(getattr(config, field), str):
            return False, f"Invalid {field}: expected text"
    if not isinstance(config.recording_retention_days, int) or isinstance(config.recording_retention_days, bool):
        return False, "Invalid recording_retention_days: expected an integer"

    # Validate AI provider
    valid_providers = ["openai", "anthropic", "openrouter", "assemblyai", "deepinfra", "local", "none"]
    if config.ai_provider not in valid_providers:
        return False, f"Invalid ai_provider: {config.ai_provider}. Must be one of {valid_providers}"
    
    # Check for API keys based on provider
    import os
    
    if config.ai_provider == "openai":
        api_key = config.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return False, (
                "ai_provider is 'openai' but no API key found.\n"
                "Set OPENAI_API_KEY environment variable or openai_api_key in config"
            )
        valid_models = ["mini", "standard"]
        if config.ai_model not in valid_models:
            return False, f"Invalid ai_model for OpenAI: {config.ai_model}. Must be one of {valid_models}"
    
    elif config.ai_provider == "anthropic":
        api_key = config.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return False, (
                "ai_provider is 'anthropic' but no API key found.\n"
                "Set ANTHROPIC_API_KEY environment variable or anthropic_api_key in config"
            )
        valid_models = ["haiku", "sonnet"]
        if config.ai_model not in valid_models:
            return False, f"Invalid ai_model for Anthropic: {config.ai_model}. Must be one of {valid_models}"
    
    elif config.ai_provider == "openrouter":
        api_key = config.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return False, (
                "ai_provider is 'openrouter' but no API key found.\n"
                "Set OPENROUTER_API_KEY environment variable or openrouter_api_key in config"
            )
        valid_models = ["cheap", "balanced", "premium"]
        if config.ai_model not in valid_models:
            return False, f"Invalid ai_model for OpenRouter: {config.ai_model}. Must be one of {valid_models}"
    
    elif config.ai_provider in ("assemblyai", "deepinfra"):
        label = {"assemblyai": "AssemblyAI", "deepinfra": "DeepInfra"}[config.ai_provider]
        valid_models = ["haiku", "sonnet", "opus"]
        if config.ai_model not in valid_models:
            return False, f"Invalid ai_model for {label}: {config.ai_model}. Must be one of {valid_models}"

    # Validate transcriber
    valid_transcribers = ["whisper", "assemblyai"]
    if config.transcriber not in valid_transcribers:
        return False, f"Invalid transcriber: {config.transcriber}. Must be one of {valid_transcribers}"

    # Validate whisper model
    valid_whisper = ["tiny", "base", "small", "medium", "large"]
    if config.whisper_model not in valid_whisper:
        return False, f"Invalid whisper_model: {config.whisper_model}. Must be one of {valid_whisper}"

    # Validate whisper device
    valid_devices = ["cpu", "cuda", "auto"]
    if config.whisper_device not in valid_devices:
        return False, f"Invalid whisper_device: {config.whisper_device}. Must be one of {valid_devices}"

    # Validate recording mode
    valid_modes = ["mic", "system", "combined"]
    if config.recording_mode not in valid_modes:
        return False, f"Invalid recording_mode: {config.recording_mode}. Must be one of {valid_modes}"
    
    # Validate directories exist or can be created (allow defaults to be auto-created)
    notes_path = Path(config.notes_dir).expanduser().absolute()
    if config.notes_dir != "notes":
        # Non-default paths must already exist
        if not notes_path.exists():
            return False, f"Notes directory does not exist: {notes_path}\nPlease create it first or use a relative path like 'notes'"
        if not notes_path.is_dir():
            return False, f"Notes path is not a directory: {notes_path}"
    
    rec_path = Path(config.recordings_dir).expanduser().absolute()
    if config.recordings_dir != "recordings":
        # Non-default paths must already exist
        if not rec_path.exists():
            return False, f"Recordings directory does not exist: {rec_path}\nPlease create it first or use a relative path like 'recordings'"
        if not rec_path.is_dir():
            return False, f"Recordings path is not a directory: {rec_path}"
    
    transcripts_path = Path(config.transcripts_dir).expanduser().absolute()
    if config.transcripts_dir != "transcripts":
        # Non-default paths must already exist
        if not transcripts_path.exists():
            return False, f"Transcripts directory does not exist: {transcripts_path}\nPlease create it first or use a relative path like 'transcripts'"
        if not transcripts_path.is_dir():
            return False, f"Transcripts path is not a directory: {transcripts_path}"
    
    return True, None


if __name__ == "__main__":
    # Test config loading/saving
    print(f"Config path: {get_config_path()}")
    
    config = load_config()
    print(f"Loaded config: {config}")
    
    valid, error = validate_config(config)
    if valid:
        print("✓ Config is valid")
    else:
        print(f"✗ Config error: {error}")
