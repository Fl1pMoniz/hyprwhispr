"""Configuration, filesystem paths and small shared helpers.

hyprwhispr stores everything under standard XDG locations:

    config   ~/.config/hyprwhispr/config.json
    data     ~/.local/share/hyprwhispr/   (whisper.cpp build, models, notes, cache)
    runtime  $XDG_RUNTIME_DIR/hyprwhispr/ (recording pid/file while in use)
    logs     ~/.local/share/hyprwhispr/logs/

All three can be overridden with environment variables so the project can be
tested or run from a non-standard location:

    HYPRWHISPR_CONFIG   full path to the config file
    HYPRWHISPR_DATA     data directory
    HYPRWHISPR_RUNTIME  runtime directory
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib

APP_NAME = "hyprwhispr"
VERSION = "1.0.0"

HOME = pathlib.Path.home()


def _xdg(env: str, default: pathlib.Path) -> pathlib.Path:
    value = os.environ.get(env)
    return pathlib.Path(value) if value else default


CONFIG_PATH = (
    pathlib.Path(os.environ["HYPRWHISPR_CONFIG"])
    if os.environ.get("HYPRWHISPR_CONFIG")
    else _xdg("XDG_CONFIG_HOME", HOME / ".config") / APP_NAME / "config.json"
)

DATA_DIR = (
    pathlib.Path(os.environ["HYPRWHISPR_DATA"])
    if os.environ.get("HYPRWHISPR_DATA")
    else _xdg("XDG_DATA_HOME", HOME / ".local/share") / APP_NAME
)

RUNTIME_DIR = (
    pathlib.Path(os.environ["HYPRWHISPR_RUNTIME"])
    if os.environ.get("HYPRWHISPR_RUNTIME")
    else pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / APP_NAME
)

NOTES_DIR = DATA_DIR / "notes"
LOGS_DIR = DATA_DIR / "logs"
CACHE_DIR = DATA_DIR / "cache"

PIDFILE = RUNTIME_DIR / "record.pid"
WAVFILE = RUNTIME_DIR / "rec.wav"
LAST_ANSWER = RUNTIME_DIR / "last-answer.txt"
LAST_TRANSCRIPT = RUNTIME_DIR / "last-transcript.txt"

DEFAULTS = {
    # --- inference (Ollama, local only) ---
    "ollama_url": "http://127.0.0.1:11434",
    "model": "qwen3:4b",
    "keep_alive": "5m",
    "num_ctx": 4096,
    "temperature": 0.3,
    # --- speech to text (whisper.cpp, local only) ---
    "whisper_bin": str(DATA_DIR / "whisper.cpp/build/bin/whisper-cli"),
    "whisper_model": str(DATA_DIR / "models/ggml-small.en.bin"),
    "whisper_gpu": True,
    "language": "en",
    # --- audio capture ---
    "sample_rate": 16000,
    "recorder": "pw-record",
    "mic_target": None,
    # --- integrations ---
    "apps": {
        "terminal": "kitty",
        "file manager": "xdg-open .",
        "browser": "xdg-open https://duckduckgo.com",
        "editor": "kitty -e nvim",
    },
    "search_url": "https://duckduckgo.com/?q=",
    "opencode_bin": "opencode",
    "terminal_bin": "kitty",
}


def ensure_dirs() -> None:
    """Create the data/runtime directories if they do not exist yet."""
    for directory in (NOTES_DIR, LOGS_DIR, CACHE_DIR, RUNTIME_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def load_config(path: pathlib.Path | None = None) -> dict:
    """Return the defaults merged with the user's config file (if any)."""
    cfg = dict(DEFAULTS)
    cfg["apps"] = dict(DEFAULTS["apps"])
    config_file = path or CONFIG_PATH
    try:
        cfg.update(json.loads(config_file.read_text()))
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        cfg.setdefault("_config_error", str(exc))
    return cfg


def save_config(cfg: dict, path: pathlib.Path | None = None) -> None:
    config_file = path or CONFIG_PATH
    config_file.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    config_file.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n")


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")
