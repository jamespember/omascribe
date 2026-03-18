#!/bin/bash
# Cloud AI setup script for Meeting Notes AI

set -e

echo "=================================="
echo "  Cloud AI Provider Setup"
echo "=================================="
echo
echo "Choose your cloud AI provider:"
echo
echo "  1) OpenAI"
echo "     - GPT-4o Mini (recommended, ~$0.002/meeting)"
echo "     - GPT-4o (premium, ~$0.03/meeting)"
echo "     - Get key at: https://platform.openai.com/api-keys"
echo
echo "  2) Anthropic"
echo "     - Claude 3.5 Haiku (recommended, ~$0.01/meeting)"
echo "     - Claude 3.5 Sonnet (premium, ~$0.03/meeting)"
echo "     - Get key at: https://console.anthropic.com/settings/keys"
echo
echo "  3) OpenRouter"
echo "     - Access 300+ models from one API"
echo "     - Gemini Flash (cheapest, ~$0.001/meeting)"
echo "     - Claude via OpenRouter (~$0.005/meeting)"
echo "     - Get key at: https://openrouter.ai/keys"
echo
echo "  4) Copilot"
echo "     - GPT-4o Mini (recommended, ~$0.002/meeting)"
echo "     - GPT-4o (premium, ~$0.03/meeting)"
echo "     - Get client key at: https://github.com/settings/applications/new"
echo
read -p "Enter choice [1-4]: " PROVIDER_CHOICE
echo

case $PROVIDER_CHOICE in
    1)
        PROVIDER="openai"
        PROVIDER_NAME="OpenAI"
        ENV_VAR="OPENAI_API_KEY"
        CONFIG_KEY="openai_api_key"
        DEFAULT_MODEL="mini"
        KEY_URL="https://platform.openai.com/api-keys"
        ;;
    2)
        PROVIDER="anthropic"
        PROVIDER_NAME="Anthropic"
        ENV_VAR="ANTHROPIC_API_KEY"
        CONFIG_KEY="anthropic_api_key"
        DEFAULT_MODEL="haiku"
        KEY_URL="https://console.anthropic.com/settings/keys"
        ;;
    3)
        PROVIDER="openrouter"
        PROVIDER_NAME="OpenRouter"
        ENV_VAR="OPENROUTER_API_KEY"
        CONFIG_KEY="openrouter_api_key"
        DEFAULT_MODEL="balanced"
        KEY_URL="https://openrouter.ai/keys"
        ;;
    4)
        PROVIDER="copilot"
        PROVIDER_NAME="Copilot"
        ENV_VAR="GITHUB_COPILOT_TOKEN"
        CONFIG_KEY="github_copilot_token"
        DEFAULT_MODEL="standard"
        KEY_URL="https://github.com/settings/tokens"
        ;;
    *)
        echo "❌ Invalid choice"
        exit 1
        ;;
esac

echo "Setting up $PROVIDER_NAME..."
echo

# Check if API key is in environment
if [ -n "${!ENV_VAR}" ]; then
    echo "✓ Found $ENV_VAR in environment"
    API_KEY="${!ENV_VAR}"
else
    echo "Enter your $PROVIDER_NAME API key:"
    echo "(Get one at: $KEY_URL)"
    echo
    read -p "API Key: " API_KEY
    
    if [ -z "$API_KEY" ]; then
        echo "❌ No API key provided"
        exit 1
    fi
    
    # Ask if they want to save to bashrc
    echo
    read -p "Save to ~/.bashrc? (y/n): " SAVE_TO_BASHRC
    
    if [ "$SAVE_TO_BASHRC" = "y" ]; then
        echo "export $ENV_VAR=\"$API_KEY\"" >> ~/.bashrc
        echo "✓ Added to ~/.bashrc (restart terminal or run: source ~/.bashrc)"
    fi
fi

echo
echo "Updating config..."

# Update config file
CONFIG_FILE="$HOME/.config/meeting-notes/config.yaml"

# Check if config already exists and warn user
if [ -f "$CONFIG_FILE" ]; then
    echo
    echo "⚠️  WARNING: Config file already exists!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo
    echo "This will OVERWRITE your existing configuration at:"
    echo "  $CONFIG_FILE"
    echo
    echo "The following settings will be RESET:"
    echo "  • AI provider (will be set based on your choice)"
    echo "  • API keys (will be overwritten)"
    echo "  • AI model (will be set to recommended default)"
    echo "  • Whisper model (will be reset to 'base')"
    echo "  • Notes directory (will be reset to ~/Documents/meeting-notes/notes)"
    echo "  • Editor (will be reset to 'nvim')"
    echo "  • Recording mode (will be reset to 'combined')"
    echo
    echo "✓ A backup will be saved to: $CONFIG_FILE.backup"
    echo
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo
    read -p "Continue and overwrite config? (y/n): " CONFIRM
    
    if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
        echo
        echo "❌ Setup cancelled. No changes made."
        echo
        echo "Tip: You can update your API key in the app by pressing ','"
        exit 0
    fi
    
    # Backup existing config
    cp "$CONFIG_FILE" "$CONFIG_FILE.backup"
    echo
    echo "✓ Backed up existing config to $CONFIG_FILE.backup"
fi

# Create or update config based on provider
cat > "$CONFIG_FILE" << EOF
# AI Summarization Settings  
ai_provider: $PROVIDER
ai_model: $DEFAULT_MODEL

# Cloud API Keys
openai_api_key: $([ "$PROVIDER" = "openai" ] && echo "\"$API_KEY\"" || echo "\"\"")
anthropic_api_key: $([ "$PROVIDER" = "anthropic" ] && echo "\"$API_KEY\"" || echo "\"\"")
openrouter_api_key: $([ "$PROVIDER" = "openrouter" ] && echo "\"$API_KEY\"" || echo "\"\"")
github_copilot_token: $([ "$PROVIDER" = "copilot" ] && echo "\"$API_KEY\"" || echo "\"\"")
github_copilot_client_id: ""

# Local Ollama (if you switch to local later)
ollama_model: llama3.2:3b

# Transcription
whisper_model: base

# Storage
notes_dir: ~/Documents/meeting-notes/notes
recordings_dir: recordings

# Editor
editor: nvim

# Recording Mode
recording_mode: combined
EOF

echo "✓ Config updated: $CONFIG_FILE"
echo "✓ Provider: $PROVIDER_NAME"
echo "✓ Default model: $DEFAULT_MODEL"
echo

# Test the setup
echo "Testing $PROVIDER_NAME API connection..."
echo

source venv/bin/activate
python3 - "$PROVIDER" "$API_KEY" "$DEFAULT_MODEL" << 'PYEOF'
import os
import sys

provider = sys.argv[1]
api_key = sys.argv[2]
model = sys.argv[3]

try:
    from meeting_notes import ai_summarizer
    
    # Test connection based on provider
    print(f"Testing {provider.upper()} connection...")
    
    if provider == "openai":
        from meeting_notes.ai_summarizer import OpenAISummarizer
        summarizer = OpenAISummarizer(api_key=api_key, model=model)
        print(f"\n✓ Connected successfully to OpenAI!")
        print(f"✓ Using model: {summarizer.model_config['name']}")
        print(f"\nTypical meeting costs:")
        print(f"  Short (5 min, ~500 words):  $0.001 - $0.003")
        print(f"  Medium (30 min, ~5k words): $0.010 - $0.030")
        print(f"  Long (1 hour, ~10k words):  $0.020 - $0.060")
        
    elif provider == "anthropic":
        from meeting_notes.ai_summarizer import AnthropicSummarizer
        summarizer = AnthropicSummarizer(api_key=api_key, model=model)
        print(f"\n✓ Connected successfully to Anthropic!")
        print(f"✓ Using model: {summarizer.model_config['name']}")
        print(f"\nTypical meeting costs:")
        print(f"  Short (5 min, ~500 words):  $0.002 - $0.008")
        print(f"  Medium (30 min, ~5k words): $0.015 - $0.050")
        print(f"  Long (1 hour, ~10k words):  $0.030 - $0.100")
        
    elif provider == "openrouter":
        from meeting_notes.ai_summarizer import OpenRouterSummarizer
        summarizer = OpenRouterSummarizer(api_key=api_key, model=model)
        print(f"\n✓ Connected successfully to OpenRouter!")
        print(f"✓ Using model: {summarizer.model_config['name']}")
        print(f"\nTypical meeting costs:")
        print(f"  Short (5 min, ~500 words):  $0.001 - $0.005")
        print(f"  Medium (30 min, ~5k words): $0.005 - $0.025")
        print(f"  Long (1 hour, ~10k words):  $0.010 - $0.050")
    
    elif provider == "copilot":
        from meeting_notes.ai_summarizer import CopilotSummarizer
        summarizer = CopilotSummarizer(api_key=api_key, model=model)
        print(f"\n✓ Connected successfully to Copilot!")
        print(f"✓ Using model: {summarizer.model_config['name']}")
        print(f"\nTypical meeting costs:")
        print(f"  Included with your active GitHub Copilot subscription")

    print("\n🎉 Setup complete! Your meetings will now be summarized in seconds!")
    sys.exit(0)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    print("\nMake sure:")
    print("  1. Your API key is correct")
    print("  2. You have internet connection")
    print(f"  3. Run: pip install {provider}")
    sys.exit(1)
PYEOF

echo
echo "=================================="
echo "  Next Steps"
echo "=================================="
echo
echo "1. Start recording meetings:"
echo "   python run.py"
echo
echo "2. Keyboard shortcuts:"
echo "   r - Start recording"
echo "   s - Stop and process"
echo "   , - Settings (change model anytime)"
echo
echo "3. Enjoy fast AI summaries! ⚡"
echo
echo "Note: You can change models or providers anytime in settings (press ',')"
echo
echo "1. Start recording meetings:"
echo "   python run.py"
echo
echo "2. Press 'r' to start, 's' to stop"
echo
echo "3. Enjoy fast AI summaries! ⚡"
echo
echo "Tip: Check out OPENROUTER_SETUP.md for more details"
