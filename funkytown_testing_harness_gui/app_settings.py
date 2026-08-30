"""Persistent GUI settings - a plain local JSON file, not the OS registry/
QSettings, so it's easy to see/edit/back up by hand. Local-machine-specific,
gitignored.
"""

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "gui_settings.json"

DEFAULTS = {
    "server": "http://127.0.0.1:8000",
    "comfyui_install_dir": "",
    "funkytown_testing_harness_dir": "",  # blank = auto-detect sibling directory
    "comfy_prompt_tools_dir": "",  # blank = let funkytown_testing_harness auto-detect its own sibling
    "hide_explicit_aspects": True,  # Settings > Hide Explicit - hides prompt_aspect_vocab.json's _explicit_aspects from the Variations tab's checklist
}


def load_settings():
    if SETTINGS_PATH.is_file():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    return {**DEFAULTS, **data}


def save_settings(settings):
    merged = {**DEFAULTS, **settings}
    SETTINGS_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
