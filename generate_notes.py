#!/usr/bin/env python3
"""
D&D Session Note Generator
Usage: python generate_notes.py <audio_file> --session <number> [--date YYYY-MM-DD]

Configure via environment variables (set by app.py from config.json):
  OBSIDIAN_VAULT   - Full path to your Obsidian campaign folder
  PARTY_MEMBERS    - Comma-separated list of character names
  CAMPAIGN_NAME    - Your campaign name (for display only)
  GEMINI_API_KEY   - Your Gemini API key
"""

import os
import sys
import argparse

# Ensure stdout/stderr can handle Unicode filenames and characters on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import whisper
from datetime import datetime
from pathlib import Path

# ── Windows: make sure ffmpeg is findable via imageio-ffmpeg ──────────────────
if os.name == "nt":
    try:
        import imageio_ffmpeg
        _ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    except ImportError:
        print("WARNING: imageio-ffmpeg not installed — ffmpeg must be in system PATH.", flush=True)
# ─────────────────────────────────────────────────────────────────────────────

# ── Config from environment variables (set by app.py) ────────────────────────
VAULT_PATH    = Path(os.environ.get("OBSIDIAN_VAULT", str(Path.home() / "obsidian-vault")))
CAMPAIGN_NAME = os.environ.get("CAMPAIGN_NAME", "My Campaign")
_party_raw    = os.environ.get("PARTY_MEMBERS", "")
PARTY_MEMBERS = [m.strip() for m in _party_raw.split(",") if m.strip()]

AI_PROVIDER  = os.environ.get("AI_PROVIDER", "gemini")
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

AI_OUTPUT_PATH     = VAULT_PATH / "AI Output"
SESSION_NOTES_PATH = VAULT_PATH / "Session Notes"
# ─────────────────────────────────────────────────────────────────────────────

# ── Default note template ─────────────────────────────────────────────────────
# Placeholders substituted at generation time:
#   {CAMPAIGN_NAME}   {DATE}   {SESSION}   {GAME_TIME}   {PARTY_SECTIONS}
DEFAULT_TEMPLATE = """\
## **Session Notes — {CAMPAIGN_NAME}**

---

**📅 Session Date:** {DATE}
**🎲 Session Number:** {SESSION}
**⏳ Game Time:** {GAME_TIME}

---

### **📖 Recap of Last Session**

(A brief summary of what happened in the previous session to refresh your memory.)

---

### **📝 Quick Notes**

(A space for quick thoughts, reminders, or things you want to remember for later.)

---

{PARTY_SECTIONS}

---

### **💭 Personal Theories & Predictions**

(A section for jotting down thoughts on ongoing storylines, possible betrayals, hidden connections, etc.)

---

### **📜 Quest Log & Tasks**

- **Main Quest:** [Current Objective]
- **Side Quests:** [Any ongoing smaller objectives?]
- **Personal Goals:** [Anything your character is working toward?]

---

### **📝 Major Events & Decisions**

- **Main Quest Progression:** (What happened related to the main storyline?)
- **Side Quests / Personal Character Arcs:** (Any updates on ongoing side stories?)
- **Notable Player Decisions:** (What choices did the players make that will affect the world?)
- **Combat Encounters:** (Who/what did the players fight? Outcome?)

---

### **🎭 Key NPCs Encountered**

- **Name:** [NPC Name]
    - **Role/Faction:** [Faction, Job, etc.]
    - **Description:** [Appearance, personality traits]
    - **Motivation/Secrets:** [What drives them? Any hidden agendas?]
    - **Recent Interaction:** [How did the party interact with them?]

---

### **🗺️ Locations & Points of Interest**

- **Location:** [Name of town, dungeon, etc.]
    - **Description:** (What's it like? Any key features?)
    - **Notable NPCs:** (Who lives here?)
    - **Secrets/Hidden Details:** (Any mysteries?)

---

### **💡 Clues & Mysteries**

(Any clues, cryptic hints, or mysteries the party encountered.)

---

### **🎒 Loot & Inventory Updates**

**Item:** [Item Name]
- **Owner:** [Character Name]
- **Notes:** [Use, Magical Properties, etc.]

---

### **📝 Notes for Next Session**

(Anything you want to bring up next session, like unfinished conversations or plans for downtime.)
"""
# ─────────────────────────────────────────────────────────────────────────────


def format_duration(seconds: float) -> str:
    """Convert seconds to a readable duration string like '3h 22m'."""
    if seconds <= 0:
        return "Unknown"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def build_template(date: str, session_number: int, duration_str: str = "") -> str:
    # Use custom template from env (set by app.py from config) or fall back to default
    template = os.environ.get("NOTE_TEMPLATE", "").strip() or DEFAULT_TEMPLATE

    if PARTY_MEMBERS:
        party_sections = "\n\n".join(f"### **🎲 {m} | Notes**\n" for m in PARTY_MEMBERS)
    else:
        party_sections = "### **🎲 Party Notes**\n"

    return (
        template
        .replace("{CAMPAIGN_NAME}", CAMPAIGN_NAME)
        .replace("{DATE}", date)
        .replace("{SESSION}", str(session_number))
        .replace("{GAME_TIME}", duration_str or "")
        .replace("{PARTY_SECTIONS}", party_sections)
    )


def _load_previous_notes() -> str:
    """Load all finalised notes from Session Notes/ for campaign context."""
    if not SESSION_NOTES_PATH.exists():
        return ""
    md_files = sorted(SESSION_NOTES_PATH.glob("*.md"))
    if not md_files:
        return ""
    parts = []
    for f in md_files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                parts.append(f"=== {f.name} ===\n{content}")
        except Exception:
            continue
    return "\n\n".join(parts)


def build_system_prompt(has_previous_notes: bool = False) -> str:
    if PARTY_MEMBERS:
        party_list = "\n".join(f"- {m}" for m in PARTY_MEMBERS)
    else:
        party_list = "- (No party members configured)"

    base = f"""\
You are a D&D session scribe. You will be given a raw transcript of a D&D session recording and a note template.
Your job is to fill in the template accurately based only on what happened in the transcript.

The party consists of the following player characters:
{party_list}

Guidelines:
- Be concise but complete. Use bullet points where the template uses them.
- Only include information that actually appeared in the transcript. Leave sections as-is if nothing relevant occurred.
- For per-character notes, focus on decisions, actions, or moments specific to that character.
- For NPCs, only include ones that were actually interacted with this session.
- Flag anything that sounded important but was unclear with [UNCLEAR] so the DM can review it.
- Keep the markdown formatting and emoji headers exactly as given in the template.
- Do not add sections that aren't in the template.
"""

    if has_previous_notes:
        base += """
You have been given notes from all previous sessions of this campaign in <previous_session_notes>.
Use them to maintain consistency with NPC names, locations, and ongoing storylines.
Focus on what is NEW in the current session — do not repeat facts already well-covered in earlier notes.
Reference previous sessions naturally where it adds useful context (e.g. "returned to the city they fled in Session 2").
"""

    return base


def transcribe(audio_path: str, model_size: str = "base") -> tuple[str, float]:
    """Returns (transcript_text, duration_seconds)."""
    print(f"Loading Whisper model ({model_size})...")
    model = whisper.load_model(model_size)
    print("Transcribing audio... (this may take a few minutes)")
    try:
        result = model.transcribe(audio_path, verbose=False)
    except FileNotFoundError:
        sys.exit(
            "\nERROR: ffmpeg not found. Whisper needs ffmpeg to decode audio files.\n"
            "Fix: open the DnD Notes app, click 'Setup Wizard', and install all packages.\n"
            "Or install ffmpeg manually from https://ffmpeg.org/download.html"
        )
    segments = result.get("segments", [])
    duration = segments[-1]["end"] if segments else 0.0
    return result["text"], duration


def _build_prompt(transcript: str, session_number: int, date: str, duration_str: str) -> str:
    previous_notes  = _load_previous_notes()
    has_prev        = bool(previous_notes)
    filled_template = build_template(date, session_number, duration_str)
    system_prompt   = build_system_prompt(has_previous_notes=has_prev)

    prev_block = (
        f"\n<previous_session_notes>\n{previous_notes}\n</previous_session_notes>\n"
        if has_prev else ""
    )

    return f"""\
{system_prompt}
{prev_block}
Here is the transcript for the current session:

<transcript>
{transcript}
</transcript>

Please fill in the following session notes template based on the transcript above:

<template>
{filled_template}
</template>

Return only the completed markdown note, nothing else.
"""


def _call_gemini(prompt: str) -> str:
    from google import genai as _genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set.")
        sys.exit(1)
    client = _genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="models/gemini-2.5-flash",
        contents=prompt,
    )
    return response.text


def _call_openai(prompt: str) -> str:
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        sys.exit(1)
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def _call_anthropic(prompt: str) -> str:
    import anthropic as _ant
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)
    client = _ant.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_ollama(prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(
        base_url=OLLAMA_URL.rstrip("/") + "/v1",
        api_key="ollama",
    )
    response = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def generate_notes(transcript: str, session_number: int, date: str, duration_str: str = "") -> str:
    prompt = _build_prompt(transcript, session_number, date, duration_str)
    print(f"Sending transcript to {AI_PROVIDER.capitalize()}...")
    if AI_PROVIDER == "openai":
        return _call_openai(prompt)
    elif AI_PROVIDER == "anthropic":
        return _call_anthropic(prompt)
    elif AI_PROVIDER == "ollama":
        return _call_ollama(prompt)
    else:
        return _call_gemini(prompt)


def save_outputs(transcript: str, notes: str, session_number: int, date: str) -> tuple[Path, Path]:
    AI_OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

    base_name       = f"Session {session_number:02d} - {date}"
    transcript_path = AI_OUTPUT_PATH / f"{base_name} - Transcript.txt"
    notes_path      = AI_OUTPUT_PATH / f"{base_name} - AI Draft.md"

    transcript_path.write_text(transcript, encoding="utf-8")
    notes_path.write_text(notes, encoding="utf-8")

    return transcript_path, notes_path


def main():
    # Special flag used by app.py's Reset button to fetch the default template text
    if '--print-default-template' in sys.argv:
        sys.stdout.buffer.write(DEFAULT_TEMPLATE.encode('utf-8'))
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Generate D&D session notes from audio recording.")
    parser.add_argument("audio_file", help="Path to the session recording")
    parser.add_argument("--session", type=int, required=True)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--model", default="base",
                        choices=["tiny", "base", "small", "medium", "large"])
    args = parser.parse_args()

    audio_path = Path(args.audio_file)
    if not audio_path.exists():
        print(f"ERROR: Audio file not found: {audio_path}")
        sys.exit(1)

    print(f"\n=== D&D Session Note Generator ===")
    print(f"Campaign : {CAMPAIGN_NAME}")
    print(f"Vault    : {VAULT_PATH}")
    print(f"Session  : {args.session} | Date: {args.date} | Audio: {audio_path.name}\n")

    if not PARTY_MEMBERS:
        print("WARNING: No party members configured.\n")

    prev_files = list(SESSION_NOTES_PATH.glob("*.md")) if SESSION_NOTES_PATH.exists() else []
    if prev_files:
        print(f"Loading {len(prev_files)} previous session note(s) for context...")

    transcript, duration_secs = transcribe(str(audio_path), args.model)
    duration_str = format_duration(duration_secs)
    print(f"Transcription complete ({len(transcript.split())} words, {duration_str})\n")

    notes = generate_notes(transcript, args.session, args.date, duration_str)
    transcript_path, notes_path = save_outputs(transcript, notes, args.session, args.date)

    print(f"\n=== Done! ===")
    print(f"Transcript : {transcript_path}")
    print(f"AI draft   : {notes_path}")
    print(f"\nOpen in Obsidian, review the draft, then move to Session Notes when ready.")


if __name__ == "__main__":
    main()
