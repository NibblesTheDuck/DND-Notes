# D&D Notes Kit

A desktop app that records your D&D sessions and automatically generates structured session notes using AI. Drop in an audio file, click Generate — the app transcribes it with Whisper and sends it to your chosen AI to fill in a customisable notes template, then saves the output straight to your Obsidian vault.

---

## Requirements

- **Python 3.9+** — [python.org](https://python.org) (tick "Add Python to PATH" during install)
- **An AI provider** — one of:
  - Google Gemini API key (free tier available) — [aistudio.google.com](https://aistudio.google.com)
  - OpenAI API key — [platform.openai.com](https://platform.openai.com)
  - Anthropic API key — [console.anthropic.com](https://console.anthropic.com)
  - [Ollama](https://ollama.com) running locally (free, no API key needed)
- **An Obsidian vault** for your campaign notes

---

## Setup (first time only)

1. Download and unzip the release
2. Double-click `build.bat` — this builds `DnD Notes.exe` (takes ~60 seconds)
3. Launch `DnD Notes.exe`
4. Follow the setup wizard to enter your vault path, party members, and API key

After setup, you can delete `build.bat` and `launcher.py` if you like. Only `DnD Notes.exe` and the `.py` files need to stay together in the same folder.

---

## How to use

1. Record your session (any audio/video format: .mkv, .mp4, .mp3, .wav, etc.)
2. Open **D&D Notes**, select your recording file
3. Set the session number and date
4. Click **Generate Notes**
5. Watch the live log as Whisper transcribes and the AI fills in your template
6. Open your Obsidian vault — the draft appears in `AI Output/`
7. Review, edit, and move it to `Session Notes/` when happy

---

## Settings

- **AI Provider** — switch between Gemini, OpenAI, Anthropic, or Ollama at any time
- **Multiple Campaigns** — each campaign has its own vault path, party members, and template
- **Note Template** — fully customisable markdown template with placeholders (`{DATE}`, `{SESSION}`, `{PARTY_SECTIONS}`, etc.)
- **Whisper Model** — trade off speed vs. accuracy (Base recommended for most sessions)

---

## Privacy

Your `config.json` (which holds your API keys and vault path) is stored locally on your machine only and is never uploaded anywhere. The only external connections the app makes are to the AI provider you choose and to GitHub to check for updates.

---

## License

Copyright (c) 2026 NibblesTheDuck. All rights reserved. See [LICENSE](LICENSE).
