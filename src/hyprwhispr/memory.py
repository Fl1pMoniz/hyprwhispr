"""Persistent local notes and remembered preferences.

Both are plain files under the data directory, so they survive restarts and are
easy to inspect, back up or delete. Saved notes are treated as untrusted data:
they are read back only as text for the user, never executed or interpreted as
instructions.
"""

from __future__ import annotations

import json
import pathlib
import re

from . import config
from .validation import args_ok


def _prefs_path() -> pathlib.Path:
    return config.NOTES_DIR / "preferences.json"


def load_preferences() -> dict:
    try:
        return json.loads(_prefs_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def memory_context() -> str:
    """A short system-message block listing what we already know about the user."""
    prefs = load_preferences()
    if not prefs:
        return ""
    lines = "\n".join(f"- {key}: {value}" for key, value in prefs.items())
    return "Facts you already remember about the user (use them, do not re-ask):\n" + lines


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", str(text).lower()) if len(w) > 2}


def relevant_context(query: str, limit: int = 8) -> str:
    """Like :func:`memory_context`, but selects relevant preferences only.

    The mechanism is deliberately small and explainable. When there are few
    preferences they are all included (so behaviour is unchanged for typical
    users). With many preferences, only those whose key or value shares a token
    with the current request are injected, so an unrelated request does not drag
    every stored fact into the prompt. If nothing matches, the highest-scoring
    preferences are still included, bounded by *limit*, so the model is never
    left unaware of a globally useful preference.
    """
    prefs = load_preferences()
    if not prefs:
        return ""
    items = list(prefs.items())
    if len(items) <= limit:
        selected = items
    else:
        wanted = _tokens(query)

        def overlap(item: tuple[str, object]) -> int:
            key, value = item
            return len(wanted & (_tokens(key) | _tokens(str(value))))

        ranked = sorted(items, key=overlap, reverse=True)
        matched = [item for item in ranked if overlap(item) > 0][:limit]
        selected = matched or ranked[:limit]
    lines = "\n".join(f"- {key}: {value}" for key, value in selected)
    return "Facts you already remember about the user (use them, do not re-ask):\n" + lines


def tool_save_note(cfg: dict, text: str) -> str:
    if not args_ok(text, 8000):
        return "error: invalid note"
    config.NOTES_DIR.mkdir(parents=True, exist_ok=True)
    note_file = config.NOTES_DIR / "notes.md"
    with note_file.open("a") as fh:
        fh.write(f"\n- [{config.now()}] {text}\n")
    return f"saved note ({len(text)} chars) to {note_file}"


def tool_list_notes(cfg: dict, query: str = "") -> str:
    config.NOTES_DIR.mkdir(parents=True, exist_ok=True)
    needle = (query or "").lower()
    hits = []
    for note_file in sorted(config.NOTES_DIR.glob("*.md")):
        for line in note_file.read_text(errors="replace").splitlines():
            if line.strip() and (not needle or needle in line.lower()):
                hits.append(line.strip())
    hits = hits[-10:]
    return "\n".join(hits) if hits else "no matching notes"


def tool_remember(cfg: dict, key: str, value: str) -> str:
    if not args_ok(key, 120) or not args_ok(value, 2000):
        return "error: invalid key/value"
    prefs = load_preferences()
    prefs[key.strip().lower()] = value
    config.NOTES_DIR.mkdir(parents=True, exist_ok=True)
    _prefs_path().write_text(json.dumps(prefs, indent=2, ensure_ascii=False) + "\n")
    return f"remembered '{key}'"


def tool_recall(cfg: dict, key: str = "") -> str:
    prefs = load_preferences()
    wanted = (key or "").strip().lower()
    if not wanted:  # no key: list everything remembered
        if not prefs:
            return "nothing is remembered yet"
        return "remembered: " + "; ".join(f"{k}: {v}" for k, v in prefs.items())
    value = prefs.get(wanted)
    if value is not None:
        return f"{key}: {value}"
    matches = {k: v for k, v in prefs.items() if wanted in k}
    if matches:
        return "remembered: " + "; ".join(f"{k}: {v}" for k, v in matches.items())
    return f"nothing remembered for '{key}'"
