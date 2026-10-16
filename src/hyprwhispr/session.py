"""Small, bounded conversation state shared between push-to-talk invocations.

Each recording runs a fresh worker process, so there is no long-lived process to
hold context. Instead we keep a tiny JSON file under the data directory:

* the last few user/assistant turns (``history_turns``),
* the most recently referenced app/game (so "close it" can resolve),
* an optional pending clarification with its choices.

It is deliberately not a database and not permanent: the file is bounded, expires
after ``session_ttl_minutes`` of inactivity, is written atomically, and is stored
with owner-only permissions. Persistent notes/preferences live separately in
:mod:`hyprwhispr.memory`.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib

from . import config

MAX_TURN_CHARS = 2000


def _state_path() -> pathlib.Path:
    return config.STATE_DIR / "session.json"


def new_state() -> dict:
    return {"updated": None, "turns": [], "entities": {}, "pending": None}


def _expired(state: dict, ttl_minutes: int) -> bool:
    updated = state.get("updated")
    if not updated:
        return True
    try:
        when = datetime.datetime.fromisoformat(updated)
    except ValueError:
        return True
    age_minutes = (datetime.datetime.now() - when).total_seconds() / 60
    return age_minutes > ttl_minutes


def load(cfg: dict) -> dict:
    """Return the current session state, or a fresh one if missing/expired."""
    try:
        state = json.loads(_state_path().read_text())
    except (OSError, json.JSONDecodeError):
        return new_state()
    if not isinstance(state, dict) or _expired(state, int(cfg.get("session_ttl_minutes", 30))):
        return new_state()
    state.setdefault("turns", [])
    state.setdefault("entities", {})
    state.setdefault("pending", None)
    return state


def save(cfg: dict, state: dict) -> None:
    """Persist *state* atomically, bounded and with owner-only permissions."""
    config.ensure_dirs()
    limit = int(cfg.get("history_turns", 6))
    state["turns"] = state.get("turns", [])[-limit * 2:]
    state["updated"] = config.now()
    path = _state_path()
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(state, ensure_ascii=False)
    tmp.write_text(payload)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def append_turn(state: dict, role: str, content: str, limit: int = 6) -> dict:
    if not content:
        return state
    turns = state.setdefault("turns", [])
    turns.append({"role": role, "content": content[:MAX_TURN_CHARS], "ts": config.now()})
    del turns[:-limit * 2]
    return state


def history_messages(state: dict, limit: int = 6) -> list[dict]:
    """Recent turns as chat messages (user/assistant only, bounded)."""
    turns = state.get("turns", [])[-limit * 2:]
    return [{"role": t["role"], "content": t["content"]} for t in turns if t.get("content")]


def entity_context(state: dict) -> str:
    """A short system note telling the model what was referenced recently."""
    lines = []
    entities = state.get("entities", {})
    if entities.get("last_target"):
        lines.append(f"Most recently referenced application/target: {entities['last_target']}")
    if entities.get("last_game"):
        lines.append(f"Most recently referenced Steam game: {entities['last_game']}")
    pending = state.get("pending")
    if pending and pending.get("options"):
        lines.append(
            "You previously asked which of these the user meant: "
            + ", ".join(pending["options"])
            + ". If the user now names one, use it."
        )
    if not lines:
        return ""
    return "Conversation context:\n" + "\n".join(lines)


def set_pending(state: dict, options: list[str]) -> None:
    state["pending"] = {"options": options[:8]} if options else None


def clear_pending(state: dict) -> None:
    state["pending"] = None


def note_tool(state: dict, tool: str, arguments: dict, result: str) -> None:
    """Record the target of a successful app/game tool call for later reference.

    Only deterministic, controlled result strings are parsed; failures are
    ignored so a failed action never becomes a resolvable reference.
    """
    if not result or result.startswith("error") or result.startswith("ambiguous:"):
        return
    entities = state.setdefault("entities", {})
    label = _entity_from_result(result) or (arguments.get("app") or arguments.get("game") or "").strip()
    if not label:
        return
    label = label.strip()
    if tool == "launch_steam_game" or "Steam game" in result:
        entities["last_game"] = label
    if tool in ("open_app", "close_app", "launch_steam_game", "launch_opencode"):
        entities["last_target"] = label


def _entity_from_result(result: str) -> str | None:
    for prefix in ("opened ", "launched the Steam game ", "launching the Steam game "):
        if result.startswith(prefix):
            return result[len(prefix):].strip()
    if result.startswith("closed "):
        rest = result.split(":", 1)[1] if ":" in result else ""
        return rest.split(",")[0].strip() or None
    if result.startswith("sent SIGTERM to "):
        return result[len("sent SIGTERM to "):].strip()
    if result.startswith("opened OpenCode"):
        return "OpenCode"
    return None


def clear(cfg: dict) -> None:
    save(cfg, new_state())
