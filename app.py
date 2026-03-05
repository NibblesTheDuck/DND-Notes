#!/usr/bin/env python3
"""
D&D Note Generator — Windows native version
Double-click 'Launch DnD Notes.bat' to start.
"""

import os, sys, json, queue, threading, subprocess, string, hashlib, urllib.request, shutil, tempfile
from datetime import date

# Hide the console window on Windows (works even when launched via python.exe)
if os.name == 'nt':
    import ctypes
    _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if _hwnd:
        ctypes.windll.user32.ShowWindow(_hwnd, 0)
    # Tell Windows this process has its own taskbar identity (shows our icon, not Python's)
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('NibblesTheDuck.DnDNotes')
from pathlib import Path
from flask import Flask, Response, request, jsonify, redirect

app = Flask(__name__)
SCRIPT_DIR      = Path(__file__).parent
CONFIG_FILE     = SCRIPT_DIR / "config.json"
GENERATE_SCRIPT = SCRIPT_DIR / "generate_notes.py"
_tasks: dict    = {}

# ─── Version / Auto-update ────────────────────────────────────────────────────
APP_VERSION  = "1.6.2"
MANIFEST_URL = "https://raw.githubusercontent.com/NibblesTheDuck/DND-Notes/master/manifest.json"
_update_info: dict = {}   # populated by background thread if update available

def _check_for_update():
    """Background thread: fetch manifest and store update info if newer version found."""
    try:
        with urllib.request.urlopen(MANIFEST_URL, timeout=5) as resp:
            manifest = json.loads(resp.read())
        if manifest.get("version", "") > APP_VERSION:
            _update_info.update(manifest)
    except Exception:
        pass  # no internet, GitHub down, etc — silently ignore

threading.Thread(target=_check_for_update, daemon=True).start()
# ─────────────────────────────────────────────────────────────────────────────

# ─── Config ───────────────────────────────────────────────────────────────────

_DEFAULTS = {
    "setup_complete":  False,
    "active_campaign": "",
    "campaigns":       {},
    "ai_provider":     "gemini",
    "api_keys":        {"gemini": "", "openai": "", "anthropic": ""},
    "ollama_url":      "http://localhost:11434",
    "ollama_model":    "llama3.1:8b",
}

_CAMPAIGN_DEFAULTS = {
    "obsidian_vault": "",
    "party_members":  [],
    "whisper_model":  "base",
    "note_template":  "",
}

def _migrate(raw: dict) -> dict:
    """Upgrade old config formats to the current format."""
    # v1.0 → v1.4: flat single-campaign → multi-campaign
    if 'campaign_name' in raw and 'campaigns' not in raw:
        name = raw.get('campaign_name', '') or 'My Campaign'
        raw = {
            'setup_complete':  raw.get('setup_complete', False),
            'gemini_api_key':  raw.get('gemini_api_key', ''),
            'active_campaign': name,
            'campaigns': {
                name: {
                    'obsidian_vault': raw.get('obsidian_vault', ''),
                    'party_members':  raw.get('party_members', []),
                    'whisper_model':  raw.get('whisper_model', 'base'),
                    'note_template':  raw.get('note_template', ''),
                }
            },
        }
    # v1.4 → v1.5: gemini_api_key → api_keys dict
    if 'gemini_api_key' in raw:
        api_keys = raw.setdefault('api_keys', {'gemini': '', 'openai': '', 'anthropic': ''})
        if not api_keys.get('gemini'):
            api_keys['gemini'] = raw['gemini_api_key']
        del raw['gemini_api_key']
    # Ensure all api_keys subkeys exist
    if 'api_keys' in raw:
        for k in ('gemini', 'openai', 'anthropic'):
            raw['api_keys'].setdefault(k, '')
    return raw

def load_cfg() -> dict:
    raw = {}
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {**_DEFAULTS, **_migrate(raw)}

def save_cfg(updates: dict) -> dict:
    cfg = load_cfg()
    cfg.update(updates)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    return cfg

def active_camp(cfg: dict) -> dict:
    """Return the active campaign's settings, with defaults filled in."""
    name = cfg.get('active_campaign', '')
    return {**_CAMPAIGN_DEFAULTS, **cfg.get('campaigns', {}).get(name, {})}

def _new_task():
    tid = f"t{len(_tasks)+1}"
    q: queue.Queue = queue.Queue()
    _tasks[tid] = q
    return tid, q

# ─── Windows drive listing ────────────────────────────────────────────────────

def _win_drives():
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append({"name": f"{letter}:", "path": drive, "type": "dir", "ext": ""})
    return drives

def _default_browse_path():
    return str(Path.home())

# ─── HTML page wrapper ────────────────────────────────────────────────────────

def _page(title, body):
    return (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1.0'>"
        "<link rel='icon' type='image/x-icon' href='/favicon.ico'>"
        "<title>" + title + " \u2014 D&amp;D Notes</title>"
        "<style>" + _CSS + "</style>"
        "</head><body>" + body + "</body></html>"
    )

# ─── Shared CSS ───────────────────────────────────────────────────────────────

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0d0d1a; --surface: #131326; --card: #1a1a33; --border: #2c2c55;
  --accent: #3261f1; --accent-h: #4f7aff; --accent-dim: #0f2a7a;
  --text: #ede8e0; --muted: #8080aa;
  --success: #4ade80; --error: #f87171; --warn: #fbbf24;
  --log-bg: #080812; --log-text: #8a90b8;
}
html, body { background: var(--bg); color: var(--text);
  font-family: 'Segoe UI', system-ui, sans-serif; font-size: 15px; min-height: 100vh; }
body { display: flex; flex-direction: column; align-items: center; padding: 2rem 1rem 4rem; }
.page-wrap { width: 100%; max-width: 620px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  padding: 1.5rem 1.6rem; margin-bottom: 1rem; }
.card-title { font-size: .72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .09em; color: var(--muted); margin-bottom: 1.1rem;
  padding-bottom: .5rem; border-bottom: 1px solid var(--border); }
.hidden { display: none !important; }
.site-header { display: flex; align-items: center; justify-content: space-between;
  width: 100%; max-width: 620px; margin-bottom: 1.8rem; }
.hdr-left { display: flex; align-items: center; gap: .8rem; }
.hdr-icon { font-size: 2rem; }
.hdr-left h1 { font-size: 1.4rem; font-weight: 700; color: var(--accent); letter-spacing: .02em; }
.hdr-left p { font-size: .85rem; color: var(--muted); margin-top: .1rem; }
.settings-btn { background: var(--border); color: var(--muted); border: none;
  border-radius: 8px; padding: .45rem .8rem; font-size: .85rem; cursor: pointer;
  text-decoration: none; transition: background .15s, color .15s; }
.settings-btn:hover { background: #3a3a70; color: var(--text); }
.back-btn { background: transparent; color: var(--muted); border: 1px solid var(--border);
  border-radius: 8px; padding: .45rem .8rem; font-size: .85rem; cursor: pointer;
  text-decoration: none; transition: background .15s; }
.back-btn:hover { background: var(--border); }
.update-banner { display:none; background: linear-gradient(135deg,#1a1a4e,#2a2a6e);
  border: 1px solid var(--accent); border-radius: 10px; padding: .75rem 1rem;
  margin-bottom: 1rem; width: 100%; max-width: 620px; }
.update-banner .u-title { color: var(--accent); font-weight: 700; font-size: .9rem; margin-bottom: .3rem; }
.update-banner .u-log { font-size: .8rem; color: var(--muted); margin: .1rem 0; }
.update-banner .u-actions { display: flex; gap: .5rem; margin-top: .6rem; align-items: center; }
.update-banner .u-msg { font-size: .8rem; color: var(--success); display:none; }
.fg { margin-bottom: 1rem; }
label { display: block; font-size: .75rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .07em; color: var(--muted); margin-bottom: .32rem; }
input[type=text], input[type=number], input[type=date], input[type=password], select, textarea {
  background: var(--bg); border: 1px solid var(--border); color: var(--text);
  padding: .52rem .72rem; border-radius: 7px; font-size: .9rem; width: 100%;
  font-family: inherit; transition: border-color .15s; -webkit-appearance: none; appearance: none; }
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent-dim); }
input[type=date]::-webkit-calendar-picker-indicator { filter: invert(.6); cursor: pointer; }
select { cursor: pointer;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath fill='%238080aa' d='M0 0l5 6 5-6z'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right .7rem center; padding-right: 2rem; }
.irow { display: flex; gap: .45rem; align-items: stretch; }
.r2 { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
.r3 { display: grid; grid-template-columns: 1.5fr 1fr 1.3fr; gap: .75rem; }
button, .btn { cursor: pointer; border: none; border-radius: 7px;
  font-family: inherit; font-size: .9rem; padding: .52rem .85rem;
  transition: background .14s, opacity .14s; white-space: nowrap; }
.btn-primary { background: var(--accent); color: #000; font-weight: 700;
  width: 100%; padding: .75rem; font-size: 1rem; border-radius: 8px; margin-top: .2rem; }
.btn-primary:hover:not(:disabled) { background: var(--accent-h); }
.btn-primary:disabled { opacity: .4; cursor: not-allowed; }
.btn-secondary { background: var(--border); color: var(--text); }
.btn-secondary:hover { background: #3a3a70; }
.btn-ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--border); color: var(--text); }
.btn-sm { padding: .3rem .6rem; font-size: .82rem; }
.btn-inline { padding: .52rem .85rem; flex-shrink: 0; }
.steps { display: flex; align-items: center; margin-bottom: 1.8rem; }
.step-item { display: flex; flex-direction: column; align-items: center; flex: 1; position: relative; }
.step-item + .step-item::before { content: ''; position: absolute; left: -50%; top: 15px;
  width: 100%; height: 2px; background: var(--border); z-index: 0; }
.step-item.done + .step-item::before { background: var(--accent-dim); }
.step-num { width: 30px; height: 30px; border-radius: 50%; border: 2px solid var(--border);
  background: var(--bg); display: flex; align-items: center; justify-content: center;
  font-size: .8rem; font-weight: 700; color: var(--muted); z-index: 1; transition: all .3s; }
.step-item.active .step-num { border-color: var(--accent); background: var(--accent-dim); color: var(--accent); }
.step-item.done .step-num { border-color: var(--success); background: #14532d; color: var(--success); }
.step-label { font-size: .72rem; color: var(--muted); margin-top: .35rem;
  text-transform: uppercase; letter-spacing: .06em; }
.step-item.active .step-label { color: var(--accent); }
.step-item.done .step-label { color: var(--success); }
.panel { display: none; }
.panel.active { display: block; }
.pkg-list { display: flex; flex-direction: column; gap: .5rem; margin: 1rem 0; }
.pkg-item { display: flex; align-items: center; gap: .8rem; padding: .7rem 1rem;
  background: var(--bg); border: 1px solid var(--border); border-radius: 8px; }
.pkg-icon { font-size: 1.1rem; width: 1.5rem; text-align: center; flex-shrink: 0; }
.pkg-name { flex: 1; font-size: .9rem; }
.pkg-status { font-size: .8rem; color: var(--muted); }
.feedback { padding: .6rem .9rem; border-radius: 7px; font-size: .85rem;
  margin-top: .6rem; display: none; }
.feedback.ok  { background: #14532d; color: var(--success); display: block; }
.feedback.err { background: #7f1d1d; color: var(--error); display: block; }
.party-list { display: flex; flex-direction: column; gap: .4rem; margin-bottom: .5rem; }
.party-row { display: flex; gap: .4rem; align-items: center; }
.party-row input { flex: 1; }
.party-row .rm-btn { flex-shrink: 0; width: 32px; height: 32px; padding: 0;
  display: flex; align-items: center; justify-content: center;
  background: transparent; border: 1px solid var(--border); color: var(--muted);
  border-radius: 6px; font-size: 1rem; }
.party-row .rm-btn:hover { background: #7f1d1d; border-color: var(--error); color: var(--error); }
.log-hdr { display: flex; align-items: center; gap: .5rem; margin-bottom: .75rem; }
.log-hdr .lbl { font-size: .72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .09em; color: var(--muted); flex: 1; }
.status-wrap { display: flex; align-items: center; gap: .4rem; font-size: .84rem; }
.spin { width: 13px; height: 13px; border: 2px solid var(--border);
  border-top-color: var(--accent); border-radius: 50%;
  animation: spin .7s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
#log { background: var(--log-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: .85rem 1rem; font-family: 'Cascadia Code','Fira Code','Consolas',monospace;
  font-size: .78rem; line-height: 1.6; height: 260px; overflow-y: auto; color: var(--log-text); }
#log::-webkit-scrollbar { width: 5px; }
#log::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.ll { padding: 1px 0; }
.ll.ok  { color: var(--success); }
.ll.err { color: var(--error); }
.ll.hi  { color: var(--accent); }
.ll.dim { color: #4a4a80; }
#install-log { background: var(--log-bg); border: 1px solid var(--border); border-radius: 7px;
  padding: .6rem .8rem; font-family: monospace; font-size: .76rem;
  height: 120px; overflow-y: auto; color: var(--log-text); display: none; margin-top: .6rem; }
#install-log.show { display: block; }
.modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.78);
  z-index: 300; align-items: center; justify-content: center; backdrop-filter: blur(3px); }
.modal-overlay.open { display: flex; }
.modal { background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  width: min(95vw,560px); max-height: 80vh; display: flex; flex-direction: column; overflow: hidden; }
.m-head { padding: .85rem 1.2rem; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: .6rem; }
.m-head h3 { font-size: .9rem; color: var(--accent); flex: 1; }
.m-close { background: transparent; color: var(--muted); font-size: 1.1rem;
  padding: .2rem .45rem; border-radius: 5px; }
.m-close:hover { background: var(--border); color: var(--text); }
.m-path { padding: .45rem 1.2rem; border-bottom: 1px solid var(--border);
  font-family: monospace; font-size: .75rem; color: var(--muted);
  background: var(--bg); overflow-x: auto; white-space: nowrap; }
.m-folder-sel { padding: .45rem 1.2rem; border-bottom: 1px solid var(--border);
  display: none; gap: .6rem; align-items: center; background: rgba(212,160,23,.08); }
.m-folder-sel.show { display: flex; }
.m-folder-sel span { font-size: .82rem; color: var(--accent); flex: 1; }
.m-body { flex: 1; overflow-y: auto; padding: .3rem 0; }
.m-body::-webkit-scrollbar { width: 5px; }
.m-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.m-empty { text-align: center; padding: 2rem; color: var(--muted); font-size: .85rem; }
.entry { display: flex; align-items: center; gap: .65rem; padding: .46rem 1.2rem;
  cursor: pointer; font-size: .87rem; transition: background .1s; user-select: none; }
.entry:hover { background: rgba(255,255,255,.04); }
.entry.sel { background: rgba(212,160,23,.13); color: var(--accent); }
.e-icon { font-size: 1rem; flex-shrink: 0; width: 1.3rem; text-align: center; }
.e-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.e-ext { font-size: .7rem; color: var(--muted); flex-shrink: 0; }
.m-foot { padding: .65rem 1.2rem; border-top: 1px solid var(--border);
  display: flex; gap: .5rem; justify-content: flex-end; }
"""

# ─── Wizard page ──────────────────────────────────────────────────────────────

_WIZARD = """
<div class="page-wrap">
  <div style="text-align:center;margin-bottom:1.8rem">
    <img src="/logo.svg" style="height:4rem;width:auto;margin-bottom:.5rem" alt="">
    <h1 style="font-size:1.5rem;font-weight:700;color:var(--accent)">D&amp;D Note Generator</h1>
    <p style="color:var(--muted);font-size:.88rem;margin-top:.2rem">First-time setup — takes about 5 minutes</p>
  </div>

  <div class="steps">
    <div class="step-item active" id="si-1">
      <div class="step-num" id="sn-1">1</div>
      <div class="step-label">Packages</div>
    </div>
    <div class="step-item" id="si-2">
      <div class="step-num" id="sn-2">2</div>
      <div class="step-label">API Key</div>
    </div>
    <div class="step-item" id="si-3">
      <div class="step-num" id="sn-3">3</div>
      <div class="step-label">Campaign</div>
    </div>
  </div>

  <!-- Step 1: Dependencies -->
  <div id="panel-1" class="panel active">
    <div class="card">
      <div class="card-title">Install Required Packages</div>
      <p style="font-size:.88rem;color:var(--muted);margin-bottom:1rem">
        These packages power the transcription and note generation.
        They only need to be installed once and may take a few minutes.
      </p>
      <div class="pkg-list">
        <div class="pkg-item" id="pkg-whisper">
          <span class="pkg-icon" id="pi-whisper">⬜</span>
          <span class="pkg-name">openai-whisper <span style="color:var(--muted);font-size:.8rem">(transcription AI)</span></span>
          <span class="pkg-status" id="ps-whisper">Checking…</span>
        </div>
        <div class="pkg-item" id="pkg-genai">
          <span class="pkg-icon" id="pi-genai">⬜</span>
          <span class="pkg-name">google-genai <span style="color:var(--muted);font-size:.8rem">(note writing AI)</span></span>
          <span class="pkg-status" id="ps-genai">Checking…</span>
        </div>
        <div class="pkg-item" id="pkg-ffmpeg">
          <span class="pkg-icon" id="pi-ffmpeg">⬜</span>
          <span class="pkg-name">imageio-ffmpeg <span style="color:var(--muted);font-size:.8rem">(video file support)</span></span>
          <span class="pkg-status" id="ps-ffmpeg">Checking…</span>
        </div>
      </div>
      <div id="install-log"></div>
      <div style="display:flex;gap:.6rem;margin-top:1rem">
        <button id="install-btn" class="btn btn-secondary" onclick="doInstall()" style="flex:1">
          Check &amp; Install
        </button>
        <button id="next-1" class="btn btn-primary" onclick="goStep(2)" disabled style="flex:1">
          Continue →
        </button>
      </div>
    </div>
  </div>

  <!-- Step 2: API Key -->
  <div id="panel-2" class="panel">
    <div class="card">
      <div class="card-title">Gemini API Key</div>
      <p style="font-size:.88rem;color:var(--muted);margin-bottom:1rem">
        This tool uses Google's Gemini AI to write your session notes.
        Get a free key at
        <a href="https://aistudio.google.com/apikey" target="_blank"
           style="color:var(--accent)">aistudio.google.com/apikey</a>
        — no credit card required.
      </p>
      <div class="fg">
        <label>Gemini API Key</label>
        <div class="irow">
          <input type="password" id="api-key-input" placeholder="AIza…"
                 autocomplete="off" spellcheck="false" />
          <button class="btn btn-secondary btn-inline" onclick="toggleKeyVis()">Show</button>
        </div>
      </div>
      <button class="btn btn-secondary" id="test-btn" onclick="testKey()" style="width:100%">
        Test Key
      </button>
      <div class="feedback" id="key-feedback"></div>
      <div style="display:flex;gap:.6rem;margin-top:1rem">
        <button class="btn btn-ghost" onclick="goStep(1)" style="flex:1">← Back</button>
        <button id="next-2" class="btn btn-primary" onclick="goStep(3)" disabled style="flex:1">
          Continue →
        </button>
      </div>
    </div>
  </div>

  <!-- Step 3: Campaign setup -->
  <div id="panel-3" class="panel">
    <div class="card">
      <div class="card-title">Campaign Setup</div>

      <div class="fg">
        <label>Obsidian Vault Folder</label>
        <div class="irow">
          <input type="text" id="vault-input"
                 placeholder="C:\\Users\\YourName\\Documents\\Obsidian\\My Campaign"
                 spellcheck="false" readonly />
          <button class="btn btn-secondary btn-inline"
                  onclick="openBrowser('folder', function(p){ document.getElementById('vault-input').value=p; })">
            Browse…
          </button>
        </div>
        <p style="font-size:.76rem;color:var(--muted);margin-top:.3rem">
          Select your campaign's folder inside Obsidian (the specific campaign subfolder, not the vault root).
        </p>
      </div>

      <div class="fg">
        <label>Campaign Name</label>
        <input type="text" id="campaign-input" placeholder="Call of the Netherdeep" />
      </div>

      <div class="fg">
        <label>Party Members</label>
        <div class="party-list" id="party-list-w"></div>
        <button class="btn btn-secondary btn-sm" onclick="addMember('party-list-w','_wParty')" style="margin-top:.3rem">
          + Add Member
        </button>
      </div>

      <div class="fg">
        <label>Whisper Model (transcription quality)</label>
        <select id="model-w">
          <option value="tiny">Tiny — fastest, least accurate</option>
          <option value="base" selected>Base — good balance (recommended)</option>
          <option value="small">Small — more accurate, slower</option>
          <option value="medium">Medium — very accurate, slow</option>
          <option value="large">Large — best quality, very slow</option>
        </select>
      </div>

      <div style="display:flex;gap:.6rem;margin-top:.5rem">
        <button class="btn btn-ghost" onclick="goStep(2)" style="flex:1">← Back</button>
        <button class="btn btn-primary" onclick="saveAndLaunch()" style="flex:1">
          Save &amp; Launch ✓
        </button>
      </div>
    </div>
  </div>
</div>

<!-- File/folder browser modal -->
<div class="modal-overlay" id="modal-overlay" onclick="modalBgClick(event)">
  <div class="modal">
    <div class="m-head">
      <h3 id="modal-title">Browse</h3>
      <button class="m-close" onclick="closeModal()">✕</button>
    </div>
    <div class="m-path" id="modal-path"></div>
    <div class="m-folder-sel" id="modal-folder-sel">
      <span>Select current folder</span>
      <button class="btn btn-primary btn-sm" onclick="confirmFolderSel()">Select This Folder</button>
    </div>
    <div class="m-body" id="modal-body"><div class="m-empty">Loading…</div></div>
    <div class="m-foot">
      <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="modal-sel-btn" disabled onclick="confirmFileSel()">Select File</button>
    </div>
  </div>
</div>

<script>
let _currentStep = 1;
let _wParty = [''];
let _modalMode = 'file', _modalCb = null, _selPath = null, _curPath = '';

function goStep(n) {
  document.getElementById('panel-' + _currentStep).classList.remove('active');
  document.getElementById('panel-' + n).classList.add('active');
  ['si-1','si-2','si-3'].forEach((id, i) => {
    const el = document.getElementById(id);
    const sn = document.getElementById('sn-' + (i+1));
    el.classList.remove('active','done');
    if (i+1 < n) { el.classList.add('done'); sn.textContent = '✓'; }
    else if (i+1 === n) el.classList.add('active');
  });
  _currentStep = n;
}

function setPkg(id, icon, status, color) {
  document.getElementById('pi-' + id).textContent = icon;
  document.getElementById('ps-' + id).textContent = status;
  document.getElementById('pkg-' + id).style.color = color || '';
}

async function checkDeps() {
  const r = await fetch('/api/check-deps');
  const d = await r.json();
  if (d.whisper) setPkg('whisper', '✅', 'Installed', 'var(--success)');
  else           setPkg('whisper', '⬜', 'Not installed', '');
  if (d.genai)   setPkg('genai',   '✅', 'Installed', 'var(--success)');
  else           setPkg('genai',   '⬜', 'Not installed', '');
  if (d.ffmpeg)  setPkg('ffmpeg',  '✅', 'Installed', 'var(--success)');
  else           setPkg('ffmpeg',  '⬜', 'Not installed', '');
  if (d.whisper && d.genai && d.ffmpeg) {
    document.getElementById('install-btn').textContent = 'Reinstall';
    document.getElementById('next-1').disabled = false;
  }
}

async function doInstall() {
  const btn = document.getElementById('install-btn');
  btn.disabled = true;
  btn.textContent = 'Installing…';
  const log = document.getElementById('install-log');
  log.classList.add('show');
  log.innerHTML = '';
  setPkg('whisper', '⏳', 'Waiting…', 'var(--warn)');
  setPkg('genai',   '⏳', 'Waiting…', 'var(--warn)');
  setPkg('ffmpeg',  '⏳', 'Waiting…', 'var(--warn)');
  const res = await fetch('/api/start-install', {method: 'POST'});
  const {task_id} = await res.json();
  const es = new EventSource('/stream/' + task_id);
  es.onmessage = (e) => {
    const {type, text} = JSON.parse(e.data);
    if (type === 'ping') return;
    if (type === 'done') {
      es.close();
      btn.disabled = false;
      btn.textContent = 'Reinstall';
      checkDeps();
      return;
    }
    if (type === 'log') {
      if (text.startsWith('INSTALLING:')) {
        const p = text.slice(11);
        setPkg(p, '⏳', 'Installing…', 'var(--warn)');
      } else if (text.startsWith('DONE:')) {
        const p = text.slice(5);
        setPkg(p, '✅', 'Installed', 'var(--success)');
      } else if (text.startsWith('ERR:')) {
        const p = text.slice(4);
        setPkg(p, '❌', 'Failed', 'var(--error)');
      } else {
        const line = document.createElement('div');
        line.textContent = text;
        log.appendChild(line);
        log.scrollTop = log.scrollHeight;
      }
    }
  };
}

function toggleKeyVis() {
  const inp = document.getElementById('api-key-input');
  inp.type = inp.type === 'password' ? 'text' : 'password';
}

async function testKey() {
  const key = document.getElementById('api-key-input').value.trim();
  const fb  = document.getElementById('key-feedback');
  const btn = document.getElementById('test-btn');
  if (!key) { showFb(fb, false, 'Please enter your API key first.'); return; }
  btn.disabled = true; btn.textContent = 'Testing…';
  fb.className = 'feedback';
  try {
    const r = await fetch('/api/test-key', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({key}),
    });
    const d = await r.json();
    if (d.ok) {
      showFb(fb, true, '✓ Key works! Gemini responded successfully.');
      document.getElementById('next-2').disabled = false;
    } else {
      showFb(fb, false, '✗ ' + d.error);
    }
  } catch(err) { showFb(fb, false, 'Network error: ' + err.message); }
  btn.disabled = false; btn.textContent = 'Test Key';
}

function showFb(el, ok, msg) {
  el.textContent = msg;
  el.className = 'feedback ' + (ok ? 'ok' : 'err');
}

function renderParty(listId, arr) {
  const container = document.getElementById(listId);
  container.innerHTML = '';
  arr.forEach((name, i) => {
    const row = document.createElement('div');
    row.className = 'party-row';
    const inp = document.createElement('input');
    inp.type = 'text'; inp.value = name; inp.placeholder = 'Character name';
    inp.addEventListener('input', () => { arr[i] = inp.value; });
    const rm = document.createElement('button');
    rm.className = 'rm-btn'; rm.textContent = '×';
    rm.addEventListener('click', () => { arr.splice(i, 1); renderParty(listId, arr); });
    row.appendChild(inp); row.appendChild(rm);
    container.appendChild(row);
  });
}

function addMember(listId, arrName) {
  const arr = arrName === '_wParty' ? _wParty : _sParty;
  if (arr.length < 8) { arr.push(''); renderParty(listId, arr); }
}

async function saveAndLaunch() {
  const vault    = document.getElementById('vault-input').value.trim();
  const campaign = document.getElementById('campaign-input').value.trim();
  const model    = document.getElementById('model-w').value;
  const apiKey   = document.getElementById('api-key-input').value.trim();
  const members  = _wParty.filter(m => m.trim());
  if (!vault)    { alert('Please select your Obsidian vault folder.'); return; }
  if (!campaign) { alert('Please enter your campaign name.'); return; }
  await fetch('/api/config', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({setup_complete: true, campaign_name: campaign,
      obsidian_vault: vault, party_members: members,
      gemini_api_key: apiKey, whisper_model: model}),
  });
  window.location.href = '/';
}

// ── File/folder browser ──────────────────────────────────────────────────────
function openBrowser(mode, cb) {
  _modalMode = mode; _modalCb = cb; _selPath = null;
  document.getElementById('modal-title').textContent =
    mode === 'folder' ? '📁 Select Campaign Folder' : '🎬 Browse for Recording';
  document.getElementById('modal-sel-btn').style.display = mode === 'folder' ? 'none' : '';
  document.getElementById('modal-sel-btn').disabled = true;
  document.getElementById('modal-overlay').classList.add('open');
  browseTo(_curPath || '');
}

function closeModal() { document.getElementById('modal-overlay').classList.remove('open'); }
function modalBgClick(e) { if (e.target.id === 'modal-overlay') closeModal(); }
function confirmFileSel() { if (_selPath && _modalCb) { _modalCb(_selPath); closeModal(); } }
function confirmFolderSel() { if (_curPath && _curPath !== '' && _modalCb) { _modalCb(_curPath); closeModal(); } }

async function browseTo(path) {
  _curPath = path;
  document.getElementById('modal-path').textContent = path || 'This PC';
  document.getElementById('modal-body').innerHTML = '<div class="m-empty">Loading…</div>';
  _selPath = null;
  document.getElementById('modal-sel-btn').disabled = true;
  const fs = document.getElementById('modal-folder-sel');
  if (_modalMode === 'folder' && path) fs.classList.add('show');
  else fs.classList.remove('show');
  try {
    const url = '/browse?mode=' + _modalMode + (path ? '&path=' + encodeURIComponent(path) : '');
    const r = await fetch(url);
    const d = await r.json();
    const body = document.getElementById('modal-body');
    if (d.error) { body.innerHTML = '<div class="m-empty" style="color:var(--error)">' + d.error + '</div>'; return; }
    if (!d.entries.length) { body.innerHTML = '<div class="m-empty">Nothing here.</div>'; return; }
    body.innerHTML = '';
    d.entries.forEach(entry => {
      const div = document.createElement('div');
      div.className = 'entry';
      const icon = entry.type === 'dir'
        ? (entry.name === '..' ? '↩' : '📁')
        : (['mkv','mp4','avi','mov','webm'].includes(entry.ext) ? '🎬' : '🎵');
      const ext = entry.type === 'file'
        ? '<span class="e-ext">' + entry.name.split('.').pop().toUpperCase() + '</span>' : '';
      div.innerHTML = '<span class="e-icon">' + icon + '</span><span class="e-name">' + entry.name + '</span>' + ext;
      div.addEventListener('click', () => {
        if (entry.type === 'dir') browseTo(entry.path);
        else {
          document.querySelectorAll('.entry').forEach(e => e.classList.remove('sel'));
          div.classList.add('sel'); _selPath = entry.path;
          document.getElementById('modal-sel-btn').disabled = false;
        }
      });
      div.addEventListener('dblclick', () => { if (entry.type === 'file') confirmFileSel(); });
      body.appendChild(div);
    });
  } catch(err) {
    document.getElementById('modal-body').innerHTML =
      '<div class="m-empty" style="color:var(--error)">Error: ' + err.message + '</div>';
  }
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
renderParty('party-list-w', _wParty);
checkDeps();
</script>
"""

# ─── Main page ────────────────────────────────────────────────────────────────

_MAIN = """
<header class="site-header">
  <div class="hdr-left">
    <img src="/logo.svg" class="hdr-icon" style="height:2.6rem;width:auto" alt="">
    <div>
      <h1 id="campaign-name">D&amp;D Notes</h1>
      <p id="campaign-sub">Loading…</p>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:.6rem">
    <select id="camp-switch" title="Switch campaign" onchange="switchCampaign(this.value)"
      style="display:none;font-size:.8rem;padding:.25rem .5rem;border-radius:5px;
             background:var(--surface);color:var(--text);border:1px solid var(--border);cursor:pointer"></select>
    <a href="/settings" class="settings-btn">⚙ Settings</a>
  </div>
</header>

<div class="update-banner" id="update-banner">
  <div class="u-title" id="update-title">✦ Update available</div>
  <div id="update-changelog"></div>
  <div class="u-actions">
    <button class="btn btn-primary btn-sm" onclick="applyUpdate()">Update Now</button>
    <button class="btn btn-ghost btn-sm" onclick="dismissUpdate()">Later</button>
    <span class="u-msg" id="update-msg"></span>
  </div>
</div>

<div class="page-wrap">
  <div class="card">
    <div class="card-title">Session Details</div>
    <div class="fg">
      <label>Recording File</label>
      <div class="irow">
        <input type="text" id="audio-path" placeholder="D:\\recordings\\session.mkv"
               autocomplete="off" spellcheck="false" />
        <button class="btn btn-secondary btn-inline"
                onclick="openBrowser('file', function(p){ document.getElementById('audio-path').value=p; })">
          Browse…
        </button>
      </div>
    </div>
    <div class="r3">
      <div class="fg">
        <label>Date</label>
        <input type="date" id="session-date" />
      </div>
      <div class="fg">
        <label>Session #</label>
        <input type="number" id="session-num" value="1" min="1" max="999" />
      </div>
      <div class="fg">
        <label>Whisper Model</label>
        <select id="whisper-model">
          <option value="tiny">Tiny (fastest)</option>
          <option value="base">Base</option>
          <option value="small">Small</option>
          <option value="medium">Medium</option>
          <option value="large">Large (best)</option>
        </select>
      </div>
    </div>
    <button class="btn btn-primary" id="gen-btn" onclick="startGenerate()">
      ▶&nbsp; Generate Notes
    </button>
  </div>

  <div class="card hidden" id="log-card">
    <div class="log-hdr">
      <span class="lbl">Output</span>
      <div class="status-wrap">
        <div class="spin" id="spin"></div>
        <span id="status-txt">Starting…</span>
      </div>
    </div>
    <div id="log"></div>
  </div>
</div>

<div class="modal-overlay" id="modal-overlay" onclick="modalBgClick(event)">
  <div class="modal">
    <div class="m-head">
      <h3 id="modal-title">Browse for Recording</h3>
      <button class="m-close" onclick="closeModal()">✕</button>
    </div>
    <div class="m-path" id="modal-path"></div>
    <div class="m-folder-sel" id="modal-folder-sel">
      <span>Select current folder</span>
      <button class="btn btn-primary btn-sm" onclick="confirmFolderSel()">Select This Folder</button>
    </div>
    <div class="m-body" id="modal-body"><div class="m-empty">Loading…</div></div>
    <div class="m-foot">
      <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="modal-sel-btn" disabled onclick="confirmFileSel()">Select File</button>
    </div>
  </div>
</div>

<script>
let _modalMode = 'file', _modalCb = null, _selPath = null, _curPath = '';

function openBrowser(mode, cb) {
  _modalMode = mode; _modalCb = cb; _selPath = null;
  const cur = document.getElementById('audio-path').value.trim();
  const lastSlash = Math.max(cur.lastIndexOf('\\\\'), cur.lastIndexOf('/'));
  _curPath = cur && lastSlash > 0 ? cur.substring(0, lastSlash) : '';
  document.getElementById('modal-sel-btn').style.display = '';
  document.getElementById('modal-sel-btn').disabled = true;
  document.getElementById('modal-overlay').classList.add('open');
  browseTo(_curPath);
}
function closeModal() { document.getElementById('modal-overlay').classList.remove('open'); }
function modalBgClick(e) { if (e.target.id === 'modal-overlay') closeModal(); }
function confirmFileSel() { if (_selPath && _modalCb) { _modalCb(_selPath); closeModal(); } }
function confirmFolderSel() {}

async function browseTo(path) {
  _curPath = path;
  document.getElementById('modal-path').textContent = path || 'This PC';
  document.getElementById('modal-body').innerHTML = '<div class="m-empty">Loading…</div>';
  _selPath = null;
  document.getElementById('modal-sel-btn').disabled = true;
  document.getElementById('modal-folder-sel').classList.remove('show');
  try {
    const url = '/browse?mode=file' + (path ? '&path=' + encodeURIComponent(path) : '');
    const r = await fetch(url);
    const d = await r.json();
    const body = document.getElementById('modal-body');
    if (d.error) { body.innerHTML = '<div class="m-empty" style="color:var(--error)">' + d.error + '</div>'; return; }
    if (!d.entries.length) { body.innerHTML = '<div class="m-empty">No audio or video files here.</div>'; return; }
    body.innerHTML = '';
    d.entries.forEach(entry => {
      const div = document.createElement('div');
      div.className = 'entry';
      const icon = entry.type === 'dir' ? (entry.name === '..' ? '↩' : '📁')
        : (['mkv','mp4','avi','mov','webm'].includes(entry.ext) ? '🎬' : '🎵');
      const ext = entry.type === 'file' ? '<span class="e-ext">' + entry.name.split('.').pop().toUpperCase() + '</span>' : '';
      div.innerHTML = '<span class="e-icon">' + icon + '</span><span class="e-name">' + entry.name + '</span>' + ext;
      div.addEventListener('click', () => {
        if (entry.type === 'dir') browseTo(entry.path);
        else {
          document.querySelectorAll('.entry').forEach(e => e.classList.remove('sel'));
          div.classList.add('sel'); _selPath = entry.path;
          document.getElementById('modal-sel-btn').disabled = false;
        }
      });
      div.addEventListener('dblclick', () => { if (entry.type === 'file') confirmFileSel(); });
      body.appendChild(div);
    });
  } catch(err) {
    document.getElementById('modal-body').innerHTML =
      '<div class="m-empty" style="color:var(--error)">Error: ' + err.message + '</div>';
  }
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

function setSt(state, text) {
  document.getElementById('spin').style.display = state === 'run' ? 'block' : 'none';
  const st = document.getElementById('status-txt');
  st.textContent = text;
  st.style.color = state === 'ok' ? 'var(--success)' : state === 'err' ? 'var(--error)' : '';
}
function addLog(text, cls) {
  const log = document.getElementById('log');
  const d = document.createElement('div');
  d.className = 'll' + (cls ? ' ' + cls : '');
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
}

async function startGenerate() {
  const audioPath   = document.getElementById('audio-path').value.trim();
  const sessionNum  = document.getElementById('session-num').value;
  const sessionDate = document.getElementById('session-date').value;
  const model       = document.getElementById('whisper-model').value;
  if (!audioPath) {
    const inp = document.getElementById('audio-path');
    inp.style.borderColor = 'var(--error)'; inp.focus();
    setTimeout(() => { inp.style.borderColor = ''; }, 2500);
    return;
  }
  const btn = document.getElementById('gen-btn');
  btn.disabled = true; btn.textContent = '⏳ Running…';
  document.getElementById('log-card').classList.remove('hidden');
  document.getElementById('log').innerHTML = '';
  setSt('run', 'Starting…');
  addLog('Session ' + sessionNum + '  ·  ' + sessionDate + '  ·  ' + model + ' model', 'hi');
  addLog('File: ' + audioPath, 'dim');
  addLog('', '');
  let taskId;
  try {
    const r = await fetch('/api/generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({audio_path: audioPath, session: sessionNum, date: sessionDate, model}),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    taskId = d.task_id;
  } catch(err) {
    addLog('Failed to start: ' + err.message, 'err');
    setSt('err', 'Failed'); btn.disabled = false; btn.textContent = '▶  Generate Notes';
    return;
  }
  const es = new EventSource('/stream/' + taskId);
  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'ping') return;
    if (msg.type === 'done') {
      es.close(); btn.disabled = false; btn.textContent = '▶  Generate Notes';
      if (msg.code === 0) { setSt('ok', 'Done!'); addLog('', ''); addLog('✓ Notes saved to Obsidian.', 'ok'); }
      else { setSt('err', 'Error'); addLog('✗ Something went wrong.', 'err'); }
      return;
    }
    if (msg.type === 'log') {
      const t = msg.text, tl = t.toLowerCase();
      const cls = t.startsWith('ERROR') ? 'err' : t.startsWith('✓') || tl.includes('saved') ? 'ok'
        : t.startsWith('===') ? 'hi' : '';
      addLog(t, cls);
      if (tl.includes('transcrib')) setSt('run', 'Transcribing…');
      else if (tl.includes('gemini') || tl.includes('sending')) setSt('run', 'Sending to Gemini…');
    }
  };
  es.onerror = () => {
    es.close(); addLog('Connection lost.', 'err'); setSt('err', 'Lost connection');
    btn.disabled = false; btn.textContent = '▶  Generate Notes';
  };
}

fetch('/api/config').then(r => r.json()).then(cfg => {
  document.getElementById('campaign-name').textContent = cfg.active_campaign || 'D&D Notes';
  document.getElementById('campaign-sub').textContent = (cfg.party_members || []).join(', ') || 'No party configured';
  document.getElementById('session-date').value = new Date().toISOString().slice(0, 10);
  document.getElementById('whisper-model').value = cfg.whisper_model || 'base';
  const sel = document.getElementById('camp-switch');
  if ((cfg.campaign_names || []).length > 1) {
    cfg.campaign_names.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      if (name === cfg.active_campaign) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.style.display = '';
  }
});
async function switchCampaign(name) {
  await fetch('/api/campaigns/switch', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
  location.reload();
}

// ── Auto-update banner ─────────────────────────────────────────────────────
fetch('/api/update-status').then(r => r.json()).then(d => {
  if (!d.available) return;
  const banner = document.getElementById('update-banner');
  document.getElementById('update-title').textContent = `✦ v${d.version} available`;
  const cl = document.getElementById('update-changelog');
  (d.changelog || []).forEach(item => {
    const p = document.createElement('div'); p.className = 'u-log';
    p.textContent = '• ' + item; cl.appendChild(p);
  });
  banner.style.display = 'block';
});
async function applyUpdate() {
  const msg = document.getElementById('update-msg');
  msg.textContent = 'Updating…'; msg.style.display = 'block';
  document.querySelector('.u-actions .btn-primary').disabled = true;
  try {
    const r = await fetch('/api/apply-update', {method:'POST'});
    const d = await r.json();
    if (d.ok) {
      msg.style.color = 'var(--success)';
      msg.textContent = '✓ Updated — restart the app to finish';
      document.querySelector('.u-actions .btn-ghost').style.display = 'none';
    } else {
      msg.style.color = 'var(--error)';
      msg.textContent = '✗ ' + d.error;
      document.querySelector('.u-actions .btn-primary').disabled = false;
    }
  } catch(e) {
    msg.style.color = 'var(--error)';
    msg.textContent = '✗ Network error: ' + e.message;
    document.querySelector('.u-actions .btn-primary').disabled = false;
  }
}
function dismissUpdate() {
  document.getElementById('update-banner').style.display = 'none';
}
</script>
"""

# ─── Settings page ────────────────────────────────────────────────────────────

_SETTINGS = """
<div style="width:100%;max-width:620px;margin-bottom:1.5rem;display:flex;align-items:center;gap:1rem">
  <a href="/" class="back-btn">← Back</a>
  <h1 style="font-size:1.3rem;font-weight:700;color:var(--accent)">Settings</h1>
</div>
<div class="page-wrap">
  <div class="card">
    <div class="card-title">AI Provider</div>
    <div class="fg">
      <label>Provider for Note Generation</label>
      <select id="s-provider" onchange="onProviderChange()">
        <option value="gemini">Google Gemini (gemini-2.5-flash)</option>
        <option value="openai">OpenAI (gpt-4o)</option>
        <option value="anthropic">Anthropic (claude-sonnet-4-6)</option>
        <option value="ollama">Ollama — Local / Free</option>
      </select>
    </div>
    <div id="s-apikey-section">
      <div class="fg">
        <label>API Key</label>
        <div class="irow">
          <input type="password" id="s-apikey" placeholder="Paste your API key…" autocomplete="off" spellcheck="false" />
          <button class="btn btn-secondary btn-inline" onclick="toggleKeyVis()">Show</button>
        </div>
      </div>
      <button class="btn btn-secondary" onclick="testKey()" style="width:100%">Test Key</button>
    </div>
    <div id="s-ollama-section" style="display:none">
      <div class="fg">
        <label>Ollama Server URL</label>
        <input type="text" id="s-ollama-url" placeholder="http://localhost:11434" spellcheck="false" />
      </div>
      <div class="fg">
        <label>Model Name</label>
        <input type="text" id="s-ollama-model" placeholder="llama3.1:8b" spellcheck="false" />
        <div style="font-size:.75rem;color:var(--muted);margin-top:.25rem">Run <code style="background:var(--input-bg);padding:.1rem .3rem;border-radius:4px">ollama pull llama3.1:8b</code> to download a model.</div>
      </div>
      <button class="btn btn-secondary" onclick="testOllama()" style="width:100%">Test Connection</button>
    </div>
    <div class="feedback" id="s-keyfb"></div>
  </div>
  <div class="card">
    <div class="card-title">Campaign</div>
    <div class="fg">
      <label>Active Campaign</label>
      <div class="irow">
        <select id="s-campaign-switch" style="flex:1" onchange="onCampaignSwitch(this.value)"></select>
        <button class="btn btn-secondary btn-inline" onclick="newCampaign()">+ New</button>
      </div>
    </div>
    <div class="fg">
      <label>Campaign Name</label>
      <input type="text" id="s-campaign" placeholder="My Campaign" />
      <div style="font-size:.75rem;color:var(--muted);margin-top:.25rem">Edit to rename this campaign.</div>
    </div>
    <div class="fg">
      <label>Obsidian Vault Folder</label>
      <div class="irow">
        <input type="text" id="s-vault" spellcheck="false" readonly
               placeholder="C:\\Users\\YourName\\Documents\\Obsidian\\Campaign" />
        <button class="btn btn-secondary btn-inline"
                onclick="openBrowser('folder', function(p){ document.getElementById('s-vault').value=p; })">
          Browse…
        </button>
      </div>
    </div>
    <div class="fg">
      <label>Party Members</label>
      <div class="party-list" id="party-list-s"></div>
      <button class="btn btn-secondary btn-sm" onclick="addMember()" style="margin-top:.3rem">+ Add Member</button>
    </div>
    <div class="fg">
      <label>Default Whisper Model</label>
      <select id="s-model">
        <option value="tiny">Tiny — fastest</option>
        <option value="base">Base — recommended</option>
        <option value="small">Small</option>
        <option value="medium">Medium</option>
        <option value="large">Large — best quality</option>
      </select>
    </div>
    <button class="btn btn-ghost btn-sm" onclick="deleteCampaign()"
            style="margin-top:.4rem;color:var(--error);border-color:var(--error)">
      Delete This Campaign
    </button>
  </div>
  <div class="card">
    <div class="card-title">Note Template</div>
    <p style="font-size:.82rem;color:var(--muted);margin:0 0 .7rem;line-height:1.6">
      Customise the markdown sent to the AI. You can add, remove, or rename sections.
      Keep these placeholders wherever you want them:<br>
      <code style="background:var(--bg);padding:.1rem .35rem;border-radius:4px;font-size:.78rem">{DATE}</code>
      <code style="background:var(--bg);padding:.1rem .35rem;border-radius:4px;font-size:.78rem">{SESSION}</code>
      <code style="background:var(--bg);padding:.1rem .35rem;border-radius:4px;font-size:.78rem">{GAME_TIME}</code>
      <code style="background:var(--bg);padding:.1rem .35rem;border-radius:4px;font-size:.78rem">{CAMPAIGN_NAME}</code>
      <code style="background:var(--bg);padding:.1rem .35rem;border-radius:4px;font-size:.78rem">{PARTY_SECTIONS}</code>
    </p>
    <textarea id="s-template" rows="18" spellcheck="false"
      style="width:100%;box-sizing:border-box;font-family:monospace;font-size:.76rem;
             background:var(--bg);color:var(--text);border:1px solid var(--border);
             border-radius:6px;padding:.6rem;resize:vertical;line-height:1.5"></textarea>
    <div style="display:flex;align-items:center;gap:.7rem;margin-top:.5rem">
      <button class="btn btn-secondary btn-sm" onclick="resetTemplate()">Reset to Default</button>
      <span style="font-size:.78rem;color:var(--muted)">Saved with the button below.</span>
    </div>
  </div>
  <button class="btn btn-primary" onclick="saveSettings()">Save Settings</button>
  <div id="save-fb" style="margin-top:.6rem;font-size:.85rem;color:var(--success);display:none">✓ Saved</div>
</div>

<div class="modal-overlay" id="modal-overlay" onclick="modalBgClick(event)">
  <div class="modal">
    <div class="m-head">
      <h3 id="modal-title">Browse</h3>
      <button class="m-close" onclick="closeModal()">✕</button>
    </div>
    <div class="m-path" id="modal-path"></div>
    <div class="m-folder-sel" id="modal-folder-sel">
      <span>Select current folder</span>
      <button class="btn btn-primary btn-sm" onclick="confirmFolderSel()">Select This Folder</button>
    </div>
    <div class="m-body" id="modal-body"><div class="m-empty">Loading…</div></div>
    <div class="m-foot">
      <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="modal-sel-btn" disabled onclick="confirmFileSel()">Select</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="new-camp-overlay" onclick="if(event.target.id==='new-camp-overlay')closeNewCampModal()">
  <div class="modal" style="max-width:420px">
    <div class="m-head">
      <h3>New Campaign</h3>
      <button class="m-close" onclick="closeNewCampModal()">✕</button>
    </div>
    <div style="padding:1.2rem 1.2rem .8rem">
      <label style="font-size:.82rem;color:var(--muted);display:block;margin-bottom:.4rem">Campaign Name</label>
      <input type="text" id="new-camp-name" placeholder="e.g. Curse of Strahd"
             style="width:100%;box-sizing:border-box"
             onkeydown="if(event.key==='Enter')confirmNewCamp()" />
      <div class="feedback" id="new-camp-fb" style="margin-top:.5rem;display:none"></div>
    </div>
    <div class="m-foot">
      <button class="btn btn-ghost" onclick="closeNewCampModal()">Cancel</button>
      <button class="btn btn-primary" onclick="confirmNewCamp()">Create Campaign</button>
    </div>
  </div>
</div>

<script>
let _sParty = [];
let _modalMode = 'folder', _modalCb = null, _selPath = null, _curPath = '';

function openBrowser(mode, cb) {
  _modalMode = mode; _modalCb = cb; _selPath = null;
  document.getElementById('modal-sel-btn').style.display = mode === 'folder' ? 'none' : '';
  document.getElementById('modal-sel-btn').disabled = true;
  document.getElementById('modal-overlay').classList.add('open');
  browseTo(_curPath || '');
}
function closeModal() { document.getElementById('modal-overlay').classList.remove('open'); }
function modalBgClick(e) { if (e.target.id === 'modal-overlay') closeModal(); }
function confirmFileSel() { if (_selPath && _modalCb) { _modalCb(_selPath); closeModal(); } }
function confirmFolderSel() { if (_curPath && _modalCb) { _modalCb(_curPath); closeModal(); } }

async function browseTo(path) {
  _curPath = path;
  document.getElementById('modal-path').textContent = path || 'This PC';
  document.getElementById('modal-body').innerHTML = '<div class="m-empty">Loading…</div>';
  _selPath = null;
  document.getElementById('modal-sel-btn').disabled = true;
  const fs = document.getElementById('modal-folder-sel');
  if (_modalMode === 'folder' && path) fs.classList.add('show'); else fs.classList.remove('show');
  try {
    const url = '/browse?mode=' + _modalMode + (path ? '&path=' + encodeURIComponent(path) : '');
    const r = await fetch(url);
    const d = await r.json();
    const body = document.getElementById('modal-body');
    if (d.error) { body.innerHTML = '<div class="m-empty" style="color:var(--error)">' + d.error + '</div>'; return; }
    body.innerHTML = '';
    d.entries.forEach(entry => {
      const div = document.createElement('div');
      div.className = 'entry';
      const icon = entry.type === 'dir' ? (entry.name === '..' ? '↩' : '📁') : '📄';
      div.innerHTML = '<span class="e-icon">' + icon + '</span><span class="e-name">' + entry.name + '</span>';
      div.addEventListener('click', () => {
        if (entry.type === 'dir') browseTo(entry.path);
        else { document.querySelectorAll('.entry').forEach(e => e.classList.remove('sel')); div.classList.add('sel'); _selPath = entry.path; document.getElementById('modal-sel-btn').disabled = false; }
      });
      body.appendChild(div);
    });
    if (!d.entries.length) body.innerHTML = '<div class="m-empty">Nothing here.</div>';
  } catch(err) {
    document.getElementById('modal-body').innerHTML = '<div class="m-empty" style="color:var(--error)">Error: ' + err.message + '</div>';
  }
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

function renderParty() {
  const container = document.getElementById('party-list-s');
  container.innerHTML = '';
  _sParty.forEach((name, i) => {
    const row = document.createElement('div'); row.className = 'party-row';
    const inp = document.createElement('input'); inp.type = 'text'; inp.value = name; inp.placeholder = 'Character name';
    inp.addEventListener('input', () => { _sParty[i] = inp.value; });
    const rm = document.createElement('button'); rm.className = 'rm-btn'; rm.textContent = '×';
    rm.addEventListener('click', () => { _sParty.splice(i, 1); renderParty(); });
    row.appendChild(inp); row.appendChild(rm); container.appendChild(row);
  });
}
function addMember() { if (_sParty.length < 8) { _sParty.push(''); renderParty(); } }
function toggleKeyVis() { const inp = document.getElementById('s-apikey'); inp.type = inp.type === 'password' ? 'text' : 'password'; }

const _keyPlaceholders = {gemini:'AIza…', openai:'sk-…', anthropic:'sk-ant-…'};
const _keySaved = {gemini:false, openai:false, anthropic:false};

function onProviderChange() {
  const p = document.getElementById('s-provider').value;
  const isOllama = p === 'ollama';
  document.getElementById('s-apikey-section').style.display = isOllama ? 'none' : '';
  document.getElementById('s-ollama-section').style.display = isOllama ? '' : 'none';
  document.getElementById('s-keyfb').style.display = 'none';
  if (!isOllama) {
    const inp = document.getElementById('s-apikey');
    inp.value = '';
    inp.placeholder = _keySaved[p] ? '(saved — enter new key to change)' : (_keyPlaceholders[p] || 'Paste your API key…');
  }
}
async function testKey() {
  const key      = document.getElementById('s-apikey').value.trim();
  const provider = document.getElementById('s-provider').value;
  const fb       = document.getElementById('s-keyfb');
  if (!key) { showFb(fb, false, 'Enter your API key first.'); return; }
  showFb(fb, null, 'Testing…');
  const r = await fetch('/api/test-key', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,provider})});
  const d = await r.json();
  showFb(fb, d.ok, d.ok ? '✓ Key works!' : '✗ ' + d.error);
}
async function testOllama() {
  const url   = (document.getElementById('s-ollama-url').value.trim() || 'http://localhost:11434').replace(/\/$/, '');
  const model = document.getElementById('s-ollama-model').value.trim() || 'llama3.1:8b';
  const fb    = document.getElementById('s-keyfb');
  showFb(fb, null, 'Testing…');
  const r = await fetch('/api/test-key', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:'ollama',ollama_url:url,ollama_model:model})});
  const d = await r.json();
  showFb(fb, d.ok, d.ok ? '✓ Ollama connected — model ready!' : '✗ ' + d.error);
}
function showFb(el, ok, msg) {
  el.textContent = msg;
  el.className = 'feedback' + (ok === true ? ' ok' : ok === false ? ' err' : '');
  el.style.display = 'block';
}
async function onCampaignSwitch(name) {
  await fetch('/api/campaigns/switch', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
  location.reload();
}
function newCampaign() {
  document.getElementById('new-camp-name').value = '';
  const fb = document.getElementById('new-camp-fb');
  fb.textContent = ''; fb.style.display = 'none';
  document.getElementById('new-camp-overlay').classList.add('open');
  setTimeout(() => document.getElementById('new-camp-name').focus(), 50);
}
function closeNewCampModal() {
  document.getElementById('new-camp-overlay').classList.remove('open');
}
async function confirmNewCamp() {
  const name = document.getElementById('new-camp-name').value.trim();
  if (!name) return;
  const fb = document.getElementById('new-camp-fb');
  fb.style.display = 'none';
  const r = await fetch('/api/campaigns/new', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
  const d = await r.json();
  if (d.error) { fb.textContent = d.error; fb.className = 'feedback err'; fb.style.display = 'block'; return; }
  location.reload();
}
async function deleteCampaign() {
  const name = document.getElementById('s-campaign').value || 'this campaign';
  if (!confirm('Delete "' + name + '"? This cannot be undone.')) return;
  const r = await fetch('/api/campaigns/delete', {method:'POST'});
  const d = await r.json();
  if (d.error) { alert(d.error); return; }
  location.reload();
}
async function resetTemplate() {
  if (!confirm('Reset to the built-in default template? Any customisations will be lost.')) return;
  const r = await fetch('/api/template/default');
  const d = await r.json();
  if (d.template) document.getElementById('s-template').value = d.template;
}
async function saveSettings() {
  const vault       = document.getElementById('s-vault').value.trim();
  const campaign    = document.getElementById('s-campaign').value.trim();
  const model       = document.getElementById('s-model').value;
  const apiKey      = document.getElementById('s-apikey').value.trim();
  const provider    = document.getElementById('s-provider').value;
  const ollamaUrl   = document.getElementById('s-ollama-url').value.trim();
  const ollamaModel = document.getElementById('s-ollama-model').value.trim();
  const members     = _sParty.filter(m => m.trim());
  const template    = document.getElementById('s-template').value;
  const payload     = {campaign_name: campaign, obsidian_vault: vault, party_members: members,
                       whisper_model: model, note_template: template,
                       ai_provider: provider, ollama_url: ollamaUrl, ollama_model: ollamaModel};
  if (apiKey) payload[`api_key_${provider}`] = apiKey;
  await fetch('/api/config', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const fb = document.getElementById('save-fb');
  fb.style.display = 'block';
  setTimeout(() => { fb.style.display = 'none'; }, 3000);
}
fetch('/api/config').then(r => r.json()).then(cfg => {
  // Populate campaign switcher
  const sel = document.getElementById('s-campaign-switch');
  (cfg.campaign_names || []).forEach(name => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    if (name === cfg.active_campaign) opt.selected = true;
    sel.appendChild(opt);
  });
  document.getElementById('s-campaign').value = cfg.active_campaign || '';
  document.getElementById('s-vault').value    = cfg.obsidian_vault || '';
  document.getElementById('s-model').value    = cfg.whisper_model || 'base';
  // AI provider
  const provider = cfg.ai_provider || 'gemini';
  document.getElementById('s-provider').value = provider;
  const saved = cfg.api_keys_saved || {};
  _keySaved.gemini    = !!saved.gemini;
  _keySaved.openai    = !!saved.openai;
  _keySaved.anthropic = !!saved.anthropic;
  document.getElementById('s-ollama-url').value   = cfg.ollama_url   || 'http://localhost:11434';
  document.getElementById('s-ollama-model').value = cfg.ollama_model || 'llama3.1:8b';
  onProviderChange();
  _sParty = cfg.party_members && cfg.party_members.length ? [...cfg.party_members] : [''];
  _curPath = cfg.obsidian_vault || '';
  renderParty();
  if (cfg.note_template) {
    document.getElementById('s-template').value = cfg.note_template;
  } else {
    fetch('/api/template/default').then(r => r.json()).then(d => {
      if (d.template) document.getElementById('s-template').value = d.template;
    });
  }
});
</script>
"""

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/api/template/default', methods=['GET'])
def get_default_template():
    """Returns the built-in DEFAULT_TEMPLATE text for the Reset button."""
    try:
        result = subprocess.run(
            [sys.executable, str(GENERATE_SCRIPT), '--print-default-template'],
            capture_output=True, cwd=str(SCRIPT_DIR)
        )
        return jsonify({'template': result.stdout.decode('utf-8')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    if not load_cfg().get('setup_complete'):
        return redirect('/wizard')
    return _page('Generator', _MAIN), 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/wizard')
def wizard():
    return _page('Setup', _WIZARD), 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/settings')
def settings():
    return _page('Settings', _SETTINGS), 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'POST':
        data = request.json or {}
        cfg  = load_cfg()
        # Global keys — per-provider API keys
        api_keys = cfg.setdefault('api_keys', {'gemini': '', 'openai': '', 'anthropic': ''})
        for provider in ('gemini', 'openai', 'anthropic'):
            val = (data.get(f'api_key_{provider}') or '').strip()
            if val:
                api_keys[provider] = val
        # Legacy: wizard still posts gemini_api_key
        if data.get('gemini_api_key'):
            api_keys['gemini'] = data['gemini_api_key']
        if 'ai_provider' in data:
            cfg['ai_provider'] = data['ai_provider']
        if data.get('ollama_url'):
            cfg['ollama_url'] = data['ollama_url']
        if data.get('ollama_model'):
            cfg['ollama_model'] = data['ollama_model']
        if 'setup_complete' in data:
            cfg['setup_complete'] = data['setup_complete']
        # Campaign-specific keys
        old_name = cfg.get('active_campaign', '')
        new_name = (data.get('campaign_name', '') or old_name).strip() or old_name or 'My Campaign'
        camp = {**_CAMPAIGN_DEFAULTS, **cfg.get('campaigns', {}).get(old_name, {})}
        for key in ('obsidian_vault', 'party_members', 'whisper_model', 'note_template'):
            if key in data:
                camp[key] = data[key]
        campaigns = cfg.get('campaigns', {})
        if old_name and old_name != new_name and old_name in campaigns:
            del campaigns[old_name]
        campaigns[new_name] = camp
        cfg['campaigns']       = campaigns
        cfg['active_campaign'] = new_name
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
        return jsonify({'ok': True})
    # GET — return flat view of active campaign for the UI
    cfg  = load_cfg()
    camp = active_camp(cfg)
    api_keys = cfg.get('api_keys', {})
    return jsonify({
        'setup_complete':  cfg.get('setup_complete', False),
        'ai_provider':     cfg.get('ai_provider', 'gemini'),
        'api_keys_saved':  {k: bool(api_keys.get(k)) for k in ('gemini', 'openai', 'anthropic')},
        'ollama_url':      cfg.get('ollama_url', 'http://localhost:11434'),
        'ollama_model':    cfg.get('ollama_model', 'llama3.1:8b'),
        'active_campaign': cfg.get('active_campaign', ''),
        'campaign_names':  list(cfg.get('campaigns', {}).keys()),
        'obsidian_vault':  camp.get('obsidian_vault', ''),
        'party_members':   camp.get('party_members', []),
        'whisper_model':   camp.get('whisper_model', 'base'),
        'note_template':   camp.get('note_template', ''),
    })

@app.route('/api/campaigns/new', methods=['POST'])
def campaign_new():
    name = ((request.json or {}).get('name', '') or '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    cfg = load_cfg()
    if name in cfg.get('campaigns', {}):
        return jsonify({'error': 'A campaign with that name already exists'}), 409
    cfg.setdefault('campaigns', {})[name] = dict(_CAMPAIGN_DEFAULTS)
    cfg['active_campaign'] = name
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    return jsonify({'ok': True})

@app.route('/api/campaigns/switch', methods=['POST'])
def campaign_switch():
    name = ((request.json or {}).get('name', '') or '').strip()
    cfg  = load_cfg()
    if name not in cfg.get('campaigns', {}):
        return jsonify({'error': 'Unknown campaign'}), 404
    cfg['active_campaign'] = name
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    return jsonify({'ok': True})

@app.route('/api/campaigns/delete', methods=['POST'])
def campaign_delete():
    cfg       = load_cfg()
    campaigns = cfg.get('campaigns', {})
    if len(campaigns) <= 1:
        return jsonify({'error': 'Cannot delete the only campaign'}), 400
    name = cfg.get('active_campaign', '')
    if name in campaigns:
        del campaigns[name]
    cfg['active_campaign'] = next(iter(campaigns))
    cfg['campaigns']       = campaigns
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    return jsonify({'ok': True, 'new_active': cfg['active_campaign']})

@app.route('/api/check-deps')
def check_deps():
    results = {}
    try:
        import whisper; results['whisper'] = True       # noqa: F401,E702
    except ImportError:
        results['whisper'] = False
    try:
        from google import genai; results['genai'] = True  # noqa: F401,E702
    except ImportError:
        results['genai'] = False
    try:
        import imageio_ffmpeg; results['ffmpeg'] = True  # noqa: F401,E702
    except ImportError:
        results['ffmpeg'] = False
    return jsonify(results)

@app.route('/api/start-install', methods=['POST'])
def start_install():
    tid, q = _new_task()
    def run():
        packages = [
            ('openai-whisper',   'whisper'),
            ('google-genai',     'genai'),
            ('imageio-ffmpeg',    'ffmpeg'),
        ]
        for pip_name, short in packages:
            q.put(('log', f'INSTALLING:{short}'))
            proc = subprocess.Popen(
                [sys.executable, '-m', 'pip', 'install', pip_name, '--progress-bar=off'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            for line in proc.stdout:
                line = line.strip()
                if line:
                    q.put(('log', line))
            proc.wait()
            q.put(('log', f'{"DONE" if proc.returncode == 0 else "ERR"}:{short}'))
        q.put(('done', 0))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({'task_id': tid})

@app.route('/api/test-key', methods=['POST'])
def test_key():
    data     = request.json or {}
    key      = data.get('key', '').strip()
    provider = data.get('provider', 'gemini')

    if provider == 'gemini':
        if not key:
            return jsonify({'ok': False, 'error': 'No API key provided'})
        try:
            from google import genai as gai
            client = gai.Client(api_key=key)
            client.models.generate_content(model='models/gemini-2.5-flash', contents='Reply OK.')
            return jsonify({'ok': True})
        except ImportError:
            return jsonify({'ok': False, 'error': 'google-genai not installed yet. Complete Step 1 first.'})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)[:300]})

    elif provider == 'openai':
        if not key:
            return jsonify({'ok': False, 'error': 'No API key provided'})
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key)
            client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[{'role': 'user', 'content': 'Reply OK.'}],
                max_tokens=5,
            )
            return jsonify({'ok': True})
        except ImportError:
            return jsonify({'ok': False, 'error': 'openai package not installed. Save and restart the app.'})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)[:300]})

    elif provider == 'anthropic':
        if not key:
            return jsonify({'ok': False, 'error': 'No API key provided'})
        try:
            import anthropic as ant
            client = ant.Anthropic(api_key=key)
            client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=5,
                messages=[{'role': 'user', 'content': 'Reply OK.'}],
            )
            return jsonify({'ok': True})
        except ImportError:
            return jsonify({'ok': False, 'error': 'anthropic package not installed. Save and restart the app.'})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)[:300]})

    elif provider == 'ollama':
        ollama_url   = (data.get('ollama_url') or 'http://localhost:11434').rstrip('/')
        ollama_model = (data.get('ollama_model') or 'llama3.1:8b').strip()
        try:
            import urllib.request, json as _json
            with urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=5) as resp:
                body = _json.loads(resp.read())
            models = [m['name'] for m in body.get('models', [])]
            base = ollama_model.split(':')[0]
            if not any(m.startswith(base) for m in models):
                return jsonify({'ok': False, 'error': f'Model "{ollama_model}" not found. Run: ollama pull {ollama_model}'})
            return jsonify({'ok': True})
        except OSError:
            return jsonify({'ok': False, 'error': f"Can't connect to Ollama at {ollama_url}. Is Ollama running?"})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)[:300]})

    return jsonify({'ok': False, 'error': 'Unknown provider'})

@app.route('/api/update-status')
def update_status():
    if _update_info:
        return jsonify({
            'available': True,
            'version':   _update_info.get('version', ''),
            'changelog': _update_info.get('changelog', []),
        })
    return jsonify({'available': False})

@app.route('/api/apply-update', methods=['POST'])
def apply_update():
    if not _update_info:
        return jsonify({'error': 'No update available'}), 400
    files = _update_info.get('files', {})
    tmp_files = []
    try:
        # Download from the specific version tag so hashes always match
        version = _update_info.get('version', 'master')
        for filename, meta in files.items():
            url      = f"https://raw.githubusercontent.com/NibblesTheDuck/DND-Notes/v{version}/{filename}"
            expected = meta.get('sha256', '')
            tmp_path = SCRIPT_DIR / f"{filename}.update_tmp"
            tmp_files.append(tmp_path)
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise ValueError(f"Hash mismatch for {filename}: expected {expected[:16]}… got {actual[:16]}…")
            tmp_path.write_bytes(data)
        # All verified — now replace
        for filename in files:
            tmp_path  = SCRIPT_DIR / f"{filename}.update_tmp"
            dest_path = SCRIPT_DIR / filename
            shutil.move(str(tmp_path), str(dest_path))
        return jsonify({'ok': True})
    except Exception as exc:
        # Clean up any temp files on failure
        for p in tmp_files:
            if p.exists():
                p.unlink()
        return jsonify({'error': str(exc)}), 500

@app.route('/browse')
def browse():
    path = request.args.get('path', '').strip()
    mode = request.args.get('mode', 'file')
    AUDIO = {'.mkv', '.mp4', '.mp3', '.wav', '.m4a', '.ogg', '.flac', '.avi', '.mov', '.webm'}

    # Empty path = show drive list on Windows, home dir on other platforms
    if not path:
        if os.name == 'nt':
            return jsonify({'path': '', 'entries': _win_drives()})
        else:
            path = _default_browse_path()

    try:
        p = Path(path)
        entries = []

        # Parent directory link (don't show at drive root like C:\)
        parent = p.parent
        if str(parent) != str(p) and str(parent) != path:
            entries.append({'name': '..', 'path': str(parent), 'type': 'dir', 'ext': ''})
        elif os.name == 'nt' and str(parent) == str(p):
            # At a drive root — ".." goes back to drive list
            entries.append({'name': '..', 'path': '', 'type': 'dir', 'ext': ''})

        dirs, files = [], []
        for item in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if item.name.startswith('.'): continue
            if item.is_dir():
                dirs.append({'name': item.name, 'path': str(item), 'type': 'dir', 'ext': ''})
            elif mode == 'file' and item.is_file() and item.suffix.lower() in AUDIO:
                files.append({'name': item.name, 'path': str(item), 'type': 'file',
                               'ext': item.suffix.lstrip('.').lower()})
        entries += dirs + files
        return jsonify({'path': str(p), 'entries': entries})
    except PermissionError:
        return jsonify({'error': f'Permission denied: {path}'}), 403
    except FileNotFoundError:
        return jsonify({'error': f'Not found: {path}'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/generate', methods=['POST'])
def generate():
    data        = request.json or {}
    audio_path  = data.get('audio_path', '').strip()
    session_num = str(data.get('session', '1'))
    session_date= data.get('date', date.today().isoformat())
    model       = data.get('model', 'base')
    if not audio_path:
        return jsonify({'error': 'Audio path required'}), 400
    cfg = load_cfg()
    tid, q = _new_task()
    def run():
        try:
            camp     = active_camp(cfg)
            api_keys = cfg.get('api_keys', {})
            env = os.environ.copy()
            env['OBSIDIAN_VAULT']  = camp.get('obsidian_vault', '')
            env['CAMPAIGN_NAME']   = cfg.get('active_campaign', 'My Campaign')
            env['PARTY_MEMBERS']   = ', '.join(camp.get('party_members') or [])
            env['AI_PROVIDER']     = cfg.get('ai_provider', 'gemini')
            env['OLLAMA_URL']      = cfg.get('ollama_url', 'http://localhost:11434')
            env['OLLAMA_MODEL']    = cfg.get('ollama_model', 'llama3.1:8b')
            if api_keys.get('gemini'):
                env['GEMINI_API_KEY']    = api_keys['gemini']
            if api_keys.get('openai'):
                env['OPENAI_API_KEY']    = api_keys['openai']
            if api_keys.get('anthropic'):
                env['ANTHROPIC_API_KEY'] = api_keys['anthropic']
            if camp.get('note_template'):
                env['NOTE_TEMPLATE'] = camp['note_template']
            cmd = [sys.executable, str(GENERATE_SCRIPT),
                   audio_path, '--session', session_num,
                   '--date', session_date, '--model', model]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=env, cwd=str(SCRIPT_DIR))
            for line in proc.stdout:
                line = line.rstrip()
                if line: q.put(('log', line))
            proc.wait()
            q.put(('done', proc.returncode))
        except Exception as exc:
            q.put(('log', f'ERROR: {exc}'))
            q.put(('done', 1))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({'task_id': tid})

@app.route('/favicon.ico')
def favicon():
    ico_path = SCRIPT_DIR / 'favicon_logoai' / 'favicon.ico'
    if not ico_path.exists():
        return '', 404
    return Response(ico_path.read_bytes(), mimetype='image/x-icon',
                    headers={'Cache-Control': 'public, max-age=86400'})

@app.route('/logo.svg')
def logo_svg():
    import re
    # Find the logo file — filename may have a numeric prefix
    matches = list(SCRIPT_DIR.glob('*Logo Symbol.svg'))
    if not matches:
        return '', 404
    svg_path = matches[0]
    content = svg_path.read_text(encoding='utf-8')
    # Remove the white background rect so the logo is transparent
    content = re.sub(r'<rect\b[^>]*fill=["\']#ffffff["\'][^>]*>.*?</rect>', '', content,
                     flags=re.DOTALL | re.IGNORECASE)
    return Response(content, mimetype='image/svg+xml',
                    headers={'Cache-Control': 'public, max-age=3600'})

@app.route('/stream/<tid>')
def stream(tid):
    def _events():
        q = _tasks.get(tid)
        if q is None:
            yield 'data: {"type":"error","text":"Task not found"}\n\n'
            return
        while True:
            try:
                msg_type, msg = q.get(timeout=120)
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'
                continue
            if msg_type == 'done':
                yield f'data: {{"type":"done","code":{msg}}}\n\n'
                _tasks.pop(tid, None)
                return
            yield 'data: ' + json.dumps({'type': msg_type, 'text': msg}) + '\n\n'
    return Response(_events(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    cfg = load_cfg()
    print(f"\n{'-'*50}")
    print(f"  D&D Note Generator")
    if cfg.get('campaign_name'):
        print(f"  Campaign : {cfg['campaign_name']}")
    print(f"  Status   : {'ready' if cfg.get('setup_complete') else 'setup wizard will open'}")
    print(f"  URL      : http://localhost:5000")
    print(f"{'-'*50}\n  Opening app window...\n")

    # Run Flask in a background thread so the main thread can drive the UI window
    def _run_flask():
        app.run(debug=False, port=5000, threaded=True)

    threading.Thread(target=_run_flask, daemon=True).start()

    # Wait for Flask to be ready (up to 20 seconds)
    import time, urllib.request
    url = 'http://localhost:5000'
    for _ in range(40):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    try:
        import webview  # pywebview — isolated native window, no extensions
        window = webview.create_window(
            'D&D Notes',
            url,
            width=1100,
            height=800,
            min_size=(800, 600),
            text_select=True,
        )
        icon_path = str(SCRIPT_DIR / 'icon.ico')

        def _apply_window_icon():
            """Set taskbar + title bar icon via Windows API after window appears."""
            if os.name != 'nt' or not os.path.exists(icon_path):
                return
            import ctypes, time
            WM_SETICON = 0x0080
            LR_LOADFROMFILE = 0x10
            IMAGE_ICON = 1
            for _ in range(20):
                time.sleep(0.3)
                hwnd = ctypes.windll.user32.FindWindowW(None, 'D&D Notes')
                if hwnd:
                    break
            else:
                return
            for size, idx in ((16, 0), (48, 1)):
                hicon = ctypes.windll.user32.LoadImageW(
                    None, icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
                if hicon:
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, idx, hicon)

        threading.Thread(target=_apply_window_icon, daemon=True).start()
        webview.start(icon=icon_path if os.path.exists(icon_path) else None)
    except Exception:
        # Fallback: open in system browser if pywebview is unavailable
        import webbrowser
        webbrowser.open(url)
        input("\n  Browser opened. Press Enter here to stop the server.\n")
