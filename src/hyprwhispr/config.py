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
import re

APP_NAME = "hyprwhispr"
VERSION = "1.1.0"

#: Effective ``keep_alive`` used when the user selects the "auto" policy.
KEEP_ALIVE_DEFAULT = "5m"
_KEEP_ALIVE_RE = re.compile(r"^\d+(s|m|h)$")

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
    # --- activation ---
    # Master on/off switch (see `hyprwhispr power`). Orthogonal to model
    # residency: being enabled does NOT load the model; the first request does.
    # Defaults to on so existing configurations keep working unchanged.
    "enabled": True,
    # --- desktop context ---
    # Include the focused Hyprland window (address/class/title) in the prompt so the
    # model can resolve "this window" references. Read-only and best-effort.
    "desktop_context": True,
    # --- application selection context (Stage 3, optional) ---
    # Read the selected/active object inside the focused application via AT-SPI
    # (Linux accessibility). Needs PyGObject/pyatspi and desktop accessibility
    # enabled; otherwise it is reported as unavailable and never guessed.
    "selection_context": True,
    "a11y_python": "",            # interpreter for the AT-SPI helper; "" = auto-detect
    # Resolve a selected file manager item to a verified path via the XDG primary
    # selection (text/uri-list) using wl-clipboard. Local, and rejected unless it is
    # a single existing local file:// URI.
    "selection_clipboard": True,
    # Reading a document's *contents* is a separate, opt-in action (privacy).
    "document_read": False,
    # --- development processes (Stage 4) ---
    # Allow stop_process to gracefully stop a process (always confirmed first). Set
    # false to keep discovery read-only. Discovery is always available.
    "process_control": True,
    # --- development services (Stage 5) ---
    # Allow start/stop/restart of registered services (always confirmed first). Set
    # false to keep service discovery/status read-only. Registered in services.json.
    "service_lifecycle": True,
    # --- arbitrary command execution (Stage 6) ---
    # run_shell runs an arbitrary shell command (still confirmed). Off by default so
    # a service cannot be started through the shell; registered services use the
    # service manager instead. Enable explicitly if you need ad-hoc commands.
    "shell_control": False,
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
    "action_history": 8,           # recent tool calls remembered for follow-ups
    "app_ambiguity_margin": 150,   # score gap below which app matches are ambiguous
    # --- integrations ---
    "apps": {
        "terminal": "kitty",
        "file manager": "xdg-open .",
        "browser": "xdg-open https://duckduckgo.com",
        "editor": "kitty -e nvim",
    },
    "search_url": "https://duckduckgo.com/?q=",
    # Preferred browser executable (name or absolute path). Empty = auto-detect a
    # common browser on PATH, falling back to xdg-open/gio when none is found.
    "browser_bin": "",
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


def update_config(values: dict, path: pathlib.Path | None = None) -> dict:
    """Merge *values* into the on-disk config, preserving every other key.

    Unlike :func:`save_config` this does not materialise defaults: it reads the
    current file, applies only *values*, and writes atomically. Missing or
    malformed files are treated as an empty base so the update still succeeds.
    This keeps the activation flag from clobbering unrelated user settings (and
    vice versa) when two hyprwhispr commands run in separate processes.
    """
    config_file = path or CONFIG_PATH
    current: dict = {}
    try:
        data = json.loads(config_file.read_text())
        if isinstance(data, dict):
            current = data
    except (OSError, json.JSONDecodeError):
        current = {}
    current.update(values)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, config_file)
    return current


def is_enabled(cfg: dict) -> bool:
    """Whether ordinary assistant activity is enabled.

    Missing values default to enabled (backward compatible); common string and
    numeric falsy spellings are understood so a hand-edited config is honoured.
    """
    value = cfg.get("enabled", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "disabled")
    return True


def set_enabled(cfg: dict, enabled: bool) -> None:
    """Persist the activation flag without touching any other setting."""
    enabled = bool(enabled)
    cfg["enabled"] = enabled
    update_config({"enabled": enabled})


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def validate_keep_alive(raw: object) -> tuple[str | None, str | None]:
    """Normalise a user-supplied model-lifetime policy to an Ollama value.

    Returns ``(value, error)``. Accepted inputs:

    * ``"auto"`` (or empty)  -> the five-minute idle default (``"5m"``)
    * ``"always"``           -> ``"-1"`` (stay loaded until changed)
    * ``"0"`` / ``"none"``   -> ``"0"`` (release as soon as the current turn ends)
    * an explicit duration   -> passed through, e.g. ``"30s"``, ``"10m"``, ``"1h"``

    Only shape is validated here; Ollama applies the value.
    """
    if isinstance(raw, bool):
        return None, "keep-alive must be 'auto', 'always', '0' or a duration like '10m'"
    if isinstance(raw, (int, float)):
        raw = str(raw)
    if not isinstance(raw, str):
        return None, "keep-alive must be 'auto', 'always', '0' or a duration like '10m'"
    value = raw.strip().lower()
    if value in ("", "auto", "default"):
        return KEEP_ALIVE_DEFAULT, None
    if value in ("always", "keep", "forever", "infinite"):
        return "-1", None
    if value in ("0", "none", "unload", "off"):
        return "0", None
    if value == "-1" or _KEEP_ALIVE_RE.match(value):
        return value, None
    return None, f"invalid keep-alive {raw!r}; use 'auto', 'always', '0' or a duration like '10m'"


def keep_alive_policy(value: object) -> str:
    """A short human label for an effective ``keep_alive`` value."""
    text = str(value if value is not None else KEEP_ALIVE_DEFAULT).strip().lower()
    if text in ("", "auto"):
        text = KEEP_ALIVE_DEFAULT
    if text == "-1":
        return "always (stays loaded until changed or unloaded)"
    if text == "0":
        return "unload after each turn (released once the turn completes)"
    return f"auto: unload after {text} idle"


def keep_alive_is_unload(value: object) -> bool:
    """True when the configured policy asks for release as soon as possible."""
    return str(value if value is not None else "").strip().lower() in ("0", "none", "unload", "off")


def turn_keep_alive(value: object) -> str:
    """The ``keep_alive`` to send while a multi-step turn is in progress.

    A turn can make several inference requests (tool call -> result -> follow-up).
    Sending ``keep_alive=0`` on an intermediate request could let Ollama unload
    the model between a tool call and the next inference. So during a turn we
    always send a non-zero value; a policy of ``0`` is honoured by the caller
    *after* the whole turn completes (see ``cli._run_turn``), not mid-turn.
    """
    if keep_alive_is_unload(value):
        return KEEP_ALIVE_DEFAULT
    text = str(value if value is not None else KEEP_ALIVE_DEFAULT).strip().lower()
    if text in ("", "auto", "default"):
        return KEEP_ALIVE_DEFAULT
    return text
