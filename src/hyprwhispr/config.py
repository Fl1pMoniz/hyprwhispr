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
VERSION = "1.1.0"

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
STATE_DIR = DATA_DIR / "state"

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
    # Optional cap on generated tokens per reply (Ollama num_predict). null = no
    # cap. A cap bounds worst-case latency on models that sometimes ramble.
    "max_tokens": None,
    "request_timeout": 120,        # seconds per model request
    "max_tool_steps": 5,           # agent loop iterations before forcing an answer
    "tool_mode": "auto",           # "auto" | "native" | "json" (see docs/architecture.md)
    "model_aliases": {"small": "qwen3:4b", "large": "qwen3:8b"},
    # --- speech to text (whisper.cpp, local only) ---
    "whisper_bin": str(DATA_DIR / "whisper.cpp/build/bin/whisper-cli"),
    # Multilingual model (ggml-small.bin). The English-only ggml-small.en.bin was
    # the old default; point whisper_model at it to force English-only behaviour.
    "whisper_model": str(DATA_DIR / "models/ggml-small.bin"),
    "whisper_gpu": True,
    "whisper_timeout": 120,        # seconds before a transcription is aborted
    # null / "" / "auto" -> detect the spoken language automatically. Any other
    # value is passed through to whisper.cpp as its ISO-639 code (e.g. "en", "pt").
    "language": None,
    # --- audio capture ---
    "sample_rate": 16000,
    "recorder": "pw-record",
    "mic_target": None,
    "min_record_ms": 300,          # ignore shorter holds (accidental taps)
    "silence_threshold_db": -50,   # peak level below this is treated as silence
    "keep_recordings": False,      # keep the recorded wav after processing
    # --- conversation context ---
    "history_turns": 6,            # user+assistant turns kept for the model
    "session_ttl_minutes": 30,     # context is forgotten after this idle time
    "app_ambiguity_margin": 150,   # score gap below which app matches are ambiguous
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
    "tool_timeout": 60,            # seconds for a confirmed shell command
    # --- logging privacy ---
    "log_transcripts": False,      # do not write transcript text to exchanges.log by default
    "log_tool_args": False,        # do not write tool arguments to the audit log by default
    # --- wake word (optional; disabled by default) ---
    # activation: "shortcut" (keyboard only, default) | "wake_word" | "both" | "disabled"
    "wake_word_mode": "shortcut",
    "wake_word": "дідько",         # exact Unicode phrase (Ukrainian); preserved verbatim
    "wake_word_models": {},        # phrase -> openWakeWord model id or path
    "wake_word_threshold": 0.5,    # detection score threshold (0..1)
    "wake_word_cooldown_seconds": 2.0,
    "wake_word_command_seconds": 6,  # bounded command-listening window after activation
    "wake_word_feedback": True,    # brief local notification on detection
    "wake_word_device": None,      # optional sounddevice input device name/index
    # detection backend: "auto" (prefer a matching openWakeWord model, else whisper),
    # "whisper" (reuse local whisper.cpp; works for any language, higher CPU), or
    # "openwakeword" (lower CPU; English pretrained or a custom model).
    "wake_word_engine": "auto",
    "wake_word_window_seconds": 2.5,  # rolling audio window for the whisper engine
}


def ensure_dirs() -> None:
    """Create the data/runtime directories if they do not exist yet."""
    for directory in (NOTES_DIR, LOGS_DIR, CACHE_DIR, STATE_DIR, RUNTIME_DIR):
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
