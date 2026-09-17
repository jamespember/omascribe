#!/bin/bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT_DIR/venv/bin/python"

if [[ ! -x $PYTHON ]]; then
    echo "Run ./setup.sh first to create the application environment." >&2
    exit 1
fi

echo "Cloud AI Provider Setup"
echo "  1) OpenAI"
echo "  2) Anthropic"
echo "  3) OpenRouter"
echo "  4) AssemblyAI (Claude via LLM Gateway; same key as AssemblyAI transcription)"
echo "  5) DeepInfra (Claude)"
echo "  6) GitHub Copilot"
read -r -p "Enter choice [1-6]: " provider_choice

# Copilot stores the OAuth token in the github_copilot_token field, not
# copilot_api_key — the assignment path below special-cases that.
config_field=""
case $provider_choice in
    1) provider=openai; provider_name=OpenAI; env_var=OPENAI_API_KEY; model=mini; key_url=https://platform.openai.com/api-keys ;;
    2) provider=anthropic; provider_name=Anthropic; env_var=ANTHROPIC_API_KEY; model=haiku; key_url=https://console.anthropic.com/settings/keys ;;
    3) provider=openrouter; provider_name=OpenRouter; env_var=OPENROUTER_API_KEY; model=balanced; key_url=https://openrouter.ai/keys ;;
    4) provider=assemblyai; provider_name=AssemblyAI; env_var=ASSEMBLYAI_API_KEY; model=sonnet; key_url=https://www.assemblyai.com/app/api-keys ;;
    5) provider=deepinfra; provider_name=DeepInfra; env_var=DEEPINFRA_API_KEY; model=sonnet; key_url=https://deepinfra.com/dash/api_keys ;;
    6) provider=copilot; provider_name="GitHub Copilot"; env_var=GITHUB_COPILOT_TOKEN; model=mini; key_url="https://github.com/settings/tokens (or use in-app device flow)"; config_field=github_copilot_token ;;
    *) echo "Invalid choice" >&2; exit 1 ;;
esac

api_key="${!env_var:-}"
if [[ -z $api_key ]]; then
    echo "Get a key at: $key_url"
    read -r -s -p "$provider_name API key: " api_key
    echo
fi
if [[ -z $api_key ]]; then
    echo "No API key provided." >&2
    exit 1
fi

MEETING_NOTES_PROVIDER="$provider" \
MEETING_NOTES_MODEL="$model" \
MEETING_NOTES_API_KEY="$api_key" \
MEETING_NOTES_CONFIG_FIELD="$config_field" \
"$PYTHON" <<'PY'
import os

from omascribe.config import load_config, save_config

provider = os.environ["MEETING_NOTES_PROVIDER"]
config = load_config()
config.ai_provider = provider
config.ai_model = os.environ["MEETING_NOTES_MODEL"]
# Most providers store their key in <provider>_api_key; Copilot uses
# github_copilot_token, which the shell passes via MEETING_NOTES_CONFIG_FIELD.
field = os.environ.get("MEETING_NOTES_CONFIG_FIELD") or f"{provider}_api_key"
setattr(config, field, os.environ["MEETING_NOTES_API_KEY"])
save_config(config)
PY

unset api_key
echo "$provider_name configured. The key is stored only in the private Omascribe config."
echo "Run: omascribe"
