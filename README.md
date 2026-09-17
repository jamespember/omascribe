# Omascribe

A keyboard-driven TUI for recording, transcribing, and summarising meetings on Linux.

Built specifically for [Omarchy Quattro](https://omarchy.org/) — integrates natively with the Quickshell bar, desktop notifications, and `SUPER+M` keybinding.

![TUI screenshot](docs/screenshot.png)

## Features

- **Record** — mic + system audio (PipeWire/PulseAudio)
- **Transcribe** — local Whisper (CPU, privacy-first), or AssemblyAI in the cloud with speaker labels
- **Summarise** — cloud LLM (OpenAI, Anthropic, OpenRouter, Copilot) or local Ollama
- **Write notes** — add your own context during recording for better AI summaries
- **Keyboard-driven** — Lazygit-inspired layout, no mouse required
- **Omarchy-native** — bar status, notifications, app menu, and `SUPER+M` out of the box

## Quick Start

```bash
git clone https://github.com/jamespember/omascribe.git
cd omascribe
./setup.sh
```

On Omarchy Quattro this adds:

- `SUPER + M` — launch or focus
- Apps menu entry
- **Omascribe control panel** — bar widget with live recording status, quick actions, and recent meetings
- Desktop notifications for recording events

The control panel plugin lives at `integrations/omarchy/omascribe-control/` and
is installed by `./setup.sh` into `~/.config/omarchy/plugins/`.

## Usage

```
omascribe
```

| Key | Action |
|-----|--------|
| `r` | Start recording |
| `s` | Stop and process |
| `x` | Cancel recording |
| `o` | Open in editor |
| `e` | Edit title |
| `t` | View transcript |
| `T` | Manage tags |
| `d` | Delete |
| `,` | Settings |
| `A` | Audio test |
| `q` | Quit |
| `j/k` or `↑↓` | Navigate |
| `/` | Search |
| `1` / `2` | Focus Meetings / Note pane |

During recording, write notes in the text area — they're fed to the AI as extra context.

## AI Setup

Cloud (fast, recommended):
```bash
./setup_cloud.sh
# or press `,` in the app and pick a provider
```

Local (free, private, slower):
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

Or skip AI entirely — set `ai_provider: none` in settings for transcription-only.

Claude through an OpenAI-compatible endpoint — `ai_model: haiku | sonnet | opus`:

| `ai_provider` | Key | Notes |
|---|---|---|
| `assemblyai` | `ASSEMBLYAI_API_KEY` | AssemblyAI's LLM Gateway; the same key as cloud transcription below. Model access is enabled per account. |
| `deepinfra` | `DEEPINFRA_API_KEY` | DeepInfra's OpenAI-compatible API. |

Both are small subclasses of `OpenAICompatibleSummarizer` (a base URL, an env
var and a tier → model-id table), so another OpenAI-compatible host is a few
lines.

## Cloud transcription (optional)

Local Whisper is the default. For faster transcription with **speaker
labels** (`Speaker A:` / `Speaker B:`, which also lets the summary name who
owns each action item), switch to [AssemblyAI](https://www.assemblyai.com/):

```yaml
transcriber: assemblyai       # whisper (default) | assemblyai
```

Set `ASSEMBLYAI_API_KEY` in the environment (or `assemblyai_api_key` in the
config, or Settings → AI → Transcription). The recording is uploaded as 16 kHz
mono FLAC — lossless for speech recognition and about a tenth of the WAV's
size — with retries if the connection drops. Audio leaves your machine in this
mode; use Whisper for meetings that must not.

Whisper is an install extra, so a cloud-only install needs no torch:

```bash
pip install -e ".[assemblyai]"     # cloud transcription only
pip install -e ".[all]"            # everything, including Whisper (what setup.sh installs)
```

## Output

Notes are saved as markdown in `notes/`:

```markdown
---
title: "Sprint Planning"
date: 2026-08-18
duration_seconds: 1860
word_count: 4230
tags: [meeting, auto-generated]
---

# Sprint Planning

**Date:** August 18, 2026 at 2:30 PM  
**Duration:** 31 minutes  
**Words:** 4,230

## AI Summary
...

### Action Items
- Sarah to send preview link by tomorrow morning
```

Full transcripts with timestamps are saved separately in `transcripts/`.

## Audio

**Recording modes:** `combined` (mic + system, default), `mic`, `system`

**Device selection:** Pick specific mic and output devices in Settings → Audio, or use system default.

**Audio Test** (`A` from main view) records a 5-second clip and diagnoses whether your meeting app's audio is actually hitting the captured sink. Catches common traps like Zoom routing to a different output.

## Configuration

Settings are stored in `~/.config/omascribe/config.yaml`:

```yaml
ai_provider: anthropic        # none | openai | anthropic | openrouter | assemblyai | deepinfra | copilot | local
ai_model: haiku               # haiku/sonnet | mini/standard | cheap/balanced/premium
whisper_model: base           # tiny | base | small | medium | large
whisper_device: cpu           # cpu | cuda | auto
recording_mode: combined      # mic | system | combined
editor: nvim
notes_dir: notes
transcripts_dir: transcripts
transcriber: whisper          # whisper | assemblyai
```

## Development

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[all,dev]"
pytest          # 127 tests
ruff check omascribe/ tests/
```

## License

MIT
