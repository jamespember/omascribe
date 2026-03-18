# Meeting Notes AI

A local, privacy-focused AI meeting notetaker for Linux with a keyboard-driven TUI. Record meetings, transcribe with Whisper, and generate summaries with your choice of local or cloud LLM.

## Features

- **Keyboard-driven TUI** - Lazygit-inspired interface, no mouse required
- **Audio recording** - Mic + system audio (PipeWire/PulseAudio)
- **Local transcription** - OpenAI Whisper (CPU-based, privacy-first)
- **AI summaries** - Cloud AI (OpenAI, Anthropic, OpenRouter) or local (Ollama)
- **User notes** - Write your own notes during recording to provide context to AI
- **Markdown notes** - Full transcripts with timestamps
- **Note management** - Edit titles, manage tags, search, delete
- **Settings UI** - Configure AI providers, API keys, models, paths
- **Integrations** - Editor, file manager, clipboard, Waybar status

## Quick Start

### Automated Setup (Recommended)

The easiest way to get started:

```bash
# Clone the repository
git clone https://github.com/jamespember/meeting-notes.git
cd meeting-notes

# Run the setup script
./setup.sh
```

The setup script will:
1. Check system dependencies (ffmpeg, pulseaudio)
2. Create a Python virtual environment
3. Install all Python dependencies
4. Let you choose between Cloud AI, Local AI (Ollama), or no AI

### Manual Setup

If you prefer to set up manually:

#### 1. Install System Dependencies

```bash
# Arch Linux
sudo pacman -S python python-pip ffmpeg portaudio

# Ubuntu / Debian
sudo apt install python3 python3-pip python3-venv ffmpeg portaudio19-dev pulseaudio-utils

# Your system should already have PipeWire/PulseAudio
```

#### 2. Set Up Python Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

**Note:** The first time you run transcription, Whisper will download the `base` model (~140MB).

#### 3. Set Up AI Summarization

**Option A: Cloud AI (Recommended for speed and quality)**

Run the cloud setup script:
```bash
./setup_cloud.sh
```

Or configure manually:
- Press `,` in the app → configure API key
- Supports OpenAI, Anthropic, OpenRouter, Copilot
- Keys stored in `~/.config/meeting-notes/config.yaml`

**Option B: Local AI (Free, private, but slower)**

Install Ollama:
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

**Option C: No AI (transcription only)**
- Set `ai_provider: none` in settings
- You'll get transcripts without AI summaries

### Run the Application

```bash
# Activate virtual environment (if not already active)
source venv/bin/activate

# Run the application
python run.py

# Or with development mode (preserves temp audio files):
python run.py --dev
```

## Usage

### TUI Interface

```
┌─────────────────────────┐ ┌──────────────────────────────────┐
│ Meeting Notes           │ │ Note Preview                     │
│                         │ │                                  │
│ 2026-01-15 14:04        │ │ # Website Redesign Discussion    │
│ Website Redesign...     │ │                                  │
│ (419 words)             │ │ **Date:** January 15, 2026       │
│                         │ │                                  │
│ 2026-01-14 10:30        │ │ ## AI Summary                    │
│ Sprint Planning...      │ │                                  │
│ (523 words)             │ │ The meeting discussed...         │
│                         │ │                                  │
└─────────────────────────┘ └──────────────────────────────────┘
 r Record  o Open  e Edit  t Transcript  T Tags  d Delete  , Settings
```

### Recording View

```
┌────────────────────────────────────────────────────────────────────────────┐
│                                                                            │
│  ┌──────────────────────────────┐  ┌─────────────────────────────────┐   │
│  │                              │  │ Meeting Title (optional):       │   │
│  │      🔴  RECORDING           │  │ ┌─────────────────────────────┐ │   │
│  │                              │  │ │ Weekly Team Standup_        │ │   │
│  │                              │  │ └─────────────────────────────┘ │   │
│  │         05:42                │  │                                 │   │
│  │                              │  │ Your Notes:                     │   │
│  │                              │  │ ┌─────────────────────────────┐ │   │
│  │  ┌────────────────────────┐  │  │ │ Discussing Q1 planning      │ │   │
│  │  │ 🎤🔊 Microphone +      │  │  │ │ Need to follow up with      │ │   │
│  │  │     System Audio       │  │  │ │ Sarah about budget_         │ │   │
│  │  │                        │  │  │ │                             │ │   │
│  │  │ Mic: Scarlett Solo     │  │  │ │                             │ │   │
│  │  │ (3rd Gen.) Input 1     │  │  │ │                             │ │   │
│  │  │                        │  │  │ │                             │ │   │
│  │  │ System: Scarlett Solo  │  │  │ │                             │ │   │
│  │  │ (3rd Gen.) Headphones  │  │  │ │                             │ │   │
│  │  │ / Line 1-2 (monitor)   │  │  │ │                             │ │   │
│  │  └────────────────────────┘  │  │ └─────────────────────────────┘ │   │
│  │                              │  │                                 │   │
│  └──────────────────────────────┘  └─────────────────────────────────┘   │
│                                                                            │
│  Press 's' to stop and process recording                                  │
│  Press 'x' to cancel and discard recording                                │
│  Press 'Esc' to unfocus title input                                       │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
 s Stop  x Cancel  q Quit
```

**User Notes:** While recording, you can write your own notes in the text area. These notes:
- Provide additional context to the AI when generating summaries
- Are saved in a dedicated "User Notes" section in the final markdown file
- Support markdown formatting
- Are completely optional

### Keyboard Shortcuts

**Main View:**
- `r` - Start recording
- `o` - Open in editor
- `e` - Edit title
- `t` - View transcript
- `T` - Manage tags
- `d` - Delete
- `c` - Copy content
- `p` - Copy path
- `f` - Show in file manager
- `,` - Settings
- `q` - Quit
- `↑↓` or `j/k` - Navigate list

**Recording:**
- `s` - Stop and process
- `x` - Cancel

### Settings

Press `,` to configure:
- AI provider (OpenAI, Anthropic, OpenRouter, Copilot, Ollama, none)
- API keys
- Whisper model (tiny/base/small/medium/large)
- Recording mode (mic/system/combined)
- Directories and editor

## Output Format

Notes are saved as markdown files in `notes/`:

```markdown
---
title: "Website Redesign Discussion"
date: 2026-01-15
time: "14:04"
duration_seconds: 179
word_count: 419
tags: [meeting, auto-generated, ai-summary]
---

# Website Redesign Discussion

**Date:** January 15, 2026 at 2:04 PM  
**Duration:** 2 minutes, 59 seconds  
**Words:** 419

## User Notes

Discussing Q1 planning
Need to follow up with Sarah about budget

## AI Summary

The meeting discussed the updates and changes to be made on the content 
side of a website, focusing on layout, design, and functionality. The 
conversation centered around visualizing the proposed changes and finalizing 
the details for implementation. Key stakeholders were engaged in the discussion.

### Key Points

- Review website layout and design changes
- Update badge display (G2, SOC2, ISO)
- Modify three-column layout for different engines
- Replace SN Genome with developer code section

### Action Items

- Review and finalize the updated website design and layout
- Create assets for implementation

### Decisions Made

- Retain white section for platform features and SEO
- Remove certain sections from homepage
- Keep customer testimonials with updated copy

### Participants

Charlie, [other participants]

## Full Transcript

**[00:00]** but the actual changes or the full updates are on the 
content side of things.

**[00:06]** If I actually share with you just to help you kind of 
visualize that...

**[00:12]** with what we look like, I'll share my screen right now...
```

## Hyprland/Waybar Integration

### Waybar Status Module

Shows recording status in your Waybar (idle/recording/processing).

**1. Add module to Waybar config** (`~/.config/waybar/config.jsonc`):

```jsonc
{
  "modules-right": [
    "custom/meeting-notes",
    // ... your other modules
  ],
  
  "custom/meeting-notes": {
    "exec": "/path/to/meeting-notes/hyprland/waybar-module.sh",
    "return-type": "json",
    "interval": 5,
    "format": "{}",
    "on-click": "$HOME/.local/bin/meeting-notes",
    "tooltip": true
  }
}
```

**2. Add styles** (`~/.config/waybar/style.css`):

```css
#custom-meeting-notes.recording {
  color: #ff5555;
  font-weight: bold;
}

#custom-meeting-notes.processing {
  color: #f1fa8c;
}

#custom-meeting-notes.ready {
  color: #50fa7b;
}

#custom-meeting-notes.idle {
  color: #6272a4;
  opacity: 0.6;
}
```

**3. Reload Waybar:**

```bash
killall waybar && waybar &
```

The module shows:
- 󰗠 (gray) - App not running
- 󰗠 (green) - Ready
- 󰦕 05:42 (red) - Recording with timer
- 󰄬 (yellow) - Processing

### Keybinding

Add to `~/.config/hypr/hyprlandrc`:

```conf
bind = SUPER, M, exec, $HOME/.local/bin/meeting-notes
```

## Audio Configuration

**Recording modes** (change in settings):
- `combined` - Mic + System (default, best for meetings)
- `mic` - Microphone only
- `system` - System audio only

## Roadmap

### Planned Features

- Real-time audio level meters during recording
- Advanced filtering UI (by date, tags, keywords)
- Export to PDF/DOCX formats
- Google Calendar integration (OAuth, auto-fetch meetings)
- Real-time transcription during recording

## License

MIT License - See LICENSE file for details

## Contributing

This is a personal project but suggestions and contributions are welcome!

1. Open an issue for bugs or feature requests
2. Check the roadmap above for planned features
3. Submit PRs with clear descriptions

### Running tests

```bash
# Lightweight tests (matches CI — no whisper/torch needed)
pip install pytest pytest-asyncio ruff openai anthropic openrouter pyyaml
pytest tests/test_config.py tests/test_paths_and_fallbacks.py \
       tests/test_recording_retention.py tests/test_summarizers.py
ruff check meeting_notes/ tests/

# Full suite (also runs Textual headless smoke tests; needs the full env)
pip install -e ".[all,dev]"
pytest
```

CI (`.github/workflows/ci.yml`) runs the lightweight subset on every PR.
