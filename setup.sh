#!/bin/bash
# Main setup script for Omascribe

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/venv"

echo "======================================"
echo "  Omascribe - Setup"
echo "======================================"
echo ""

# Check if already configured
CONFIG_FILE="$HOME/.config/omascribe/config.yaml"
if [ -f "$CONFIG_FILE" ]; then
    echo "ℹ️  Existing configuration detected at:"
    echo "   $CONFIG_FILE"
    echo ""
    echo "⚠️  Running this setup may overwrite your current settings."
    echo ""
    echo "If you just want to change one setting, you can:"
    echo "  • Press ',' in the app to open settings"
    echo "  • Or manually edit: $CONFIG_FILE"
    echo ""
    read -p "Continue with setup anyway? (y/n): " CONTINUE_SETUP
    
    if [ "$CONTINUE_SETUP" != "y" ] && [ "$CONTINUE_SETUP" != "Y" ]; then
        echo ""
        echo "Setup cancelled. No changes made."
        exit 0
    fi
    echo ""
fi

# Detect python command
if command -v python &> /dev/null; then
    PYTHON=python
else
    PYTHON=python3
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
    echo "Virtual environment created"
fi
PYTHON="$VENV_DIR/bin/python"
echo "Virtual environment: $VENV_DIR"
echo ""

# Check system dependencies
echo "Checking system dependencies..."

if ! command -v pactl &> /dev/null; then
    echo "ERROR: pactl not found. Please install Pulse compatibility tools:"
    echo "   Arch/Omarchy:   omarchy pkg add libpulse"
    echo "   Ubuntu/Debian:  sudo apt install pulseaudio-utils"
    echo "   Fedora/RHEL:    sudo dnf install pulseaudio-utils"
    exit 1
fi

if ! command -v parec &> /dev/null && ! command -v pw-record &> /dev/null; then
    echo "ERROR: neither parec nor pw-record was found. Install an audio capture tool:"
    echo "   Arch/Omarchy:   omarchy pkg add pipewire libpulse"
    echo "   Ubuntu/Debian:  sudo apt install pipewire-pulse pulseaudio-utils"
    echo "   Fedora/RHEL:    sudo dnf install pipewire-utils pulseaudio-utils"
    exit 1
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: ffmpeg not found. Please install it:"
    echo "   Arch:           sudo pacman -S ffmpeg"
    echo "   Ubuntu/Debian:  sudo apt install ffmpeg"
    # On stock Fedora only 'ffmpeg-free' is available (patents); the swap
    # pulls in RPM Fusion's full ffmpeg. Give the two-liner rather than
    # sending users to hunt for the incantation.
    echo "   Fedora/RHEL:    sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-\$(rpm -E %fedora).noarch.rpm \\"
    echo "                   && sudo dnf swap ffmpeg-free ffmpeg --allowerasing"
    exit 1
fi

echo "System dependencies OK"
echo ""

# Install Python dependencies
echo "Installing Python dependencies..."
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -e "$ROOT_DIR[all]"

mkdir -p "$HOME/.local/bin"
ln -sfn "$VENV_DIR/bin/omascribe" "$HOME/.local/bin/omascribe"
ln -sfn "$VENV_DIR/bin/omascribe-status" "$HOME/.local/bin/omascribe-status"
ln -sfn "$VENV_DIR/bin/omascribe-panel" "$HOME/.local/bin/omascribe-panel"

if command -v omarchy >/dev/null 2>&1 && [[ $(omarchy version) == 4.* ]]; then
    "$ROOT_DIR/integrations/omarchy/install.sh"
fi

configure_ai_provider() {
    "$PYTHON" - "$1" <<'PY'
import sys

from omascribe.config import load_config, save_config

provider = sys.argv[1]
config = load_config()
config.ai_provider = provider
if provider == "local":
    config.ai_model = config.ollama_model or "llama3.2:3b"
save_config(config)
PY
}

echo ""
echo "======================================"
echo "  AI Provider Setup"
echo "======================================"
echo ""
echo "Choose your AI summarization provider:"
echo ""
echo "  1) Cloud AI (Recommended)"
echo "     - Fast, high-quality summaries"
echo "     - Choose: OpenAI, Anthropic, or OpenRouter"
echo "     - Requires API key (~$0.01 per meeting)"
echo ""
echo "  2) Local AI (Ollama)"
echo "     - Free, runs on your machine"
echo "     - Requires Ollama installation"
echo "     - Slower, uses system resources"
echo ""
echo "  3) Skip AI setup (transcription only)"
echo "     - No summarization"
echo "     - Can configure later in settings"
echo ""

while true; do
    read -p "Enter choice [1-3]: " choice
    
    case $choice in
        1)
            echo ""
            echo "Running cloud AI setup..."
            echo ""
            echo "You'll choose between OpenAI, Anthropic, or OpenRouter."
            echo "Note: You'll be prompted before any existing settings are changed."
            echo ""
            "$ROOT_DIR/setup_cloud.sh"
            break
            ;;
        2)
            echo ""
            echo "Setting up local AI (Ollama)..."
            echo ""
            
            if ! command -v ollama &> /dev/null; then
                echo "Ollama is not installed. Install it from:"
                echo "   https://ollama.com/download/linux"
                echo "Then rerun setup or select Local from the app settings."
                configure_ai_provider none
                break
            fi
            echo "Ollama already installed"
            
            echo ""
            echo "Pulling recommended model (llama3.2:3b)..."
            ollama pull llama3.2:3b
            configure_ai_provider local
            
            echo ""
            echo "Local AI setup complete!"
            echo ""
            echo "Note: You can change the model in settings (press ',' in app)"
            break
            ;;
        3)
            echo ""
            echo "Skipping AI setup"
            configure_ai_provider none
            echo ""
            echo "You can configure AI later by:"
            echo "  - Pressing ',' in the app"
            echo "  - Or running ./setup_cloud.sh for cloud AI"
            break
            ;;
        *)
            echo "Invalid choice. Please enter 1, 2, or 3."
            ;;
    esac
done

echo ""
echo "======================================"
echo "  Setup Complete!"
echo "======================================"
echo ""
echo "To run the application:"
echo "   $HOME/.local/bin/omascribe"
echo ""
echo "Keyboard shortcuts:"
echo "   r - Start recording"
echo "   s - Stop recording"
echo "   , - Open settings"
echo "   q - Quit"
echo ""
echo "Note: First transcription will download Whisper base model (~140MB)"
echo ""
echo "For more information, see README.md"
echo ""
