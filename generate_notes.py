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
import whisper
from google import genai
from datetime import datetime
from pathlib import Path

# ── Windows: make sure ffmpeg is findable via imageio-ffmpeg ──────────────────
if os.name == "nt":
    try:
        import imageio_ffmpeg
        _ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    except ImportError:
        pass  # ffmpeg must be on PATH manually if imageio-ffmpeg isn't installed
# ─────────────────────────────────────────────────────────────────────────────

# ── Config from environment variables (set by app.py) ────────────────────────
VAULT_PATH    = Path(os.environ.get("OBSIDIAN_VAULT", str(Path.home() / "obsidian-vault")))
CAMPAIGN_NAME = os.environ.get("CAMPAIGN_NAME", "My Campaign")
_party_raw    = os.environ.get("PARTY_MEMBERS", "")
PARTY_MEMBERS = [m.strip() for m in _party_raw.split(",") if m.strip()]

AI_OUTPUT_PATH     = VAULT_PATH / "AI Output"
SESSION_NOTES_PATH = VAULT_PATH / "Session Notes"
# ─────────────────────────────────────────────────────────────────────────────


def build_template(date: str, session_number: int) -> str:
    if PARTY_MEMBERS:
        party_sections = "\n\n".join(f"### **🎲 {m} | Notes**\n" for m in PARTY_MEMBERS)
    else:
        party_sections = "### **🎲 Party Notes**\n"

    return f"""\
## **Session Notes — {CAMPAIGN_NAME}**

---

**📅 Session Date:** {date}
**🎲 Session Number:** {session_number}
**⏳ Game Time:**

---

### **📖 Recap of Last Session**

(A brief summary of what happened in the previous session to refresh your memory.)

---

### **📝 Quick Notes**

(A space for quick thoughts, reminders, or things you want to remember for later.)

---

{party_sections}

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


def build_system_prompt() -> str:
    if PARTY_MEMBERS:
        party_list = "\n".join(f"- {m}" for m in PARTY_MEMBERS)
    else:
        party_list = "- (No party members configured)"

    return f"""\
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


def transcribe(audio_path: str, model_size: str = "base") -> str:
    print(f"Loading Whisper model ({model_size})...")
    model = whisper.load_model(model_size)
    print("Transcribing audio... (this may take a few minutes)")
    result = model.transcribe(audio_path, verbose=False)
    return result["text"]


def generate_notes(transcript: str, session_number: int, date: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    filled_template = build_template(date, session_number)
    system_prompt   = build_system_prompt()

    prompt = f"""\
{system_prompt}

Here is the session transcript:

<transcript>
{transcript}
</transcript>

Please fill in the following session notes template based on the transcript above:

<template>
{filled_template}
</template>

Return only the completed markdown note, nothing else.
"""

    print("Sending transcript to Gemini...")
    response = client.models.generate_content(
        model="models/gemini-2.5-flash",
        contents=prompt,
    )
    return response.text


def save_outputs(transcript: str, notes: str, session_number: int, date: str) -> tuple[Path, Path]:
    AI_OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

    base_name       = f"Session {session_number:02d} - {date}"
    transcript_path = AI_OUTPUT_PATH / f"{base_name} - Transcript.txt"
    notes_path      = AI_OUTPUT_PATH / f"{base_name} - AI Draft.md"

    transcript_path.write_text(transcript, encoding="utf-8")
    notes_path.write_text(notes, encoding="utf-8")

    return transcript_path, notes_path


def main():
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

    transcript = transcribe(str(audio_path), args.model)
    print(f"Transcription complete ({len(transcript.split())} words)\n")

    notes = generate_notes(transcript, args.session, args.date)
    transcript_path, notes_path = save_outputs(transcript, notes, args.session, args.date)

    print(f"\n=== Done! ===")
    print(f"Transcript : {transcript_path}")
    print(f"AI draft   : {notes_path}")
    print(f"\nOpen in Obsidian, review the draft, then move to Session Notes when ready.")


if __name__ == "__main__":
    main()
