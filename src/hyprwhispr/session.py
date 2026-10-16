"""Small, bounded conversation state shared between push-to-talk invocations.

Each recording runs a fresh worker process, so there is no long-lived process to
hold context. Instead we keep a tiny JSON file under the data directory:

* the last few user/assistant turns (``history_turns``),
* the most recently referenced app/game (so "close it" can resolve),
* a bounded log of recent tool calls and their outcomes, so a later worker sees
  what was actually done (and whether it succeeded) - not just the final reply,
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
import re

from . import config

MAX_TURN_CHARS = 2000
MAX_ACTION_CHARS = 200

#: Tools whose raw output/arguments are never stored in the session file. Their
#: effect is recorded by status only, so a shell command or file path is not
#: silently persisted where transcripts/args logging is otherwise off.
SENSITIVE_TOOLS = {"run_shell", "install_package", "delete_path"}


def _state_path() -> pathlib.Path:
    return config.STATE_DIR / "session.json"


def new_state() -> dict:
    return {"updated": None, "turns": [], "entities": {}, "pending": None, "actions": []}


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
    state.setdefault("actions", [])
    return state


def save(cfg: dict, state: dict) -> None:
    """Persist *state* atomically, bounded and with owner-only permissions."""
    config.ensure_dirs()
    limit = int(cfg.get("history_turns", 6))
    state["turns"] = state.get("turns", [])[-limit * 2:]
    action_limit = int(cfg.get("action_history", 8))
    state["actions"] = state.get("actions", [])[-action_limit:]
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
        lines.append(_target_line("application/target", entities["last_target"], entities.get("last_target_ts")))
    if entities.get("last_game"):
        lines.append(_target_line("Steam game", entities["last_game"], entities.get("last_game_ts")))
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


def _target_line(kind: str, name: str, timestamp: str | None) -> str:
    """Describe a remembered target, flagging that it may have gone stale."""
    line = f"Most recently referenced {kind}: {name}"
    age = _age_minutes(timestamp)
    if age is not None:
        line += (f" (referenced about {age} min ago; it may have been closed or changed since - "
                 "do not assume it still exists, and do not claim an action succeeded "
                 "without a confirming tool result)")
    return line


def _age_minutes(timestamp: object) -> int | None:
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        when = datetime.datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return max(0, round((datetime.datetime.now() - when).total_seconds() / 60))


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
    stamp = config.now()
    if tool == "launch_steam_game" or "Steam game" in result:
        entities["last_game"] = label
        entities["last_game_ts"] = stamp
    if tool in ("open_app", "close_app", "launch_steam_game", "launch_opencode"):
        entities["last_target"] = label
        entities["last_target_ts"] = stamp


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


def record_action(state: dict, tool: str, arguments: dict, result: str, limit: int = 8) -> dict:
    """Remember one tool call and its outcome for later turns.

    The entry is deliberately compact and privacy-aware: a non-sensitive tool
    gets a short result summary, while :data:`SENSITIVE_TOOLS` record status only
    (so a shell command or file path is not silently persisted).
    """
    actions = state.setdefault("actions", [])
    tool_name = tool if isinstance(tool, str) and tool else "?"
    entry: dict = {"tool": tool_name, "status": _classify(result), "ts": config.now()}
    target = _action_target(tool_name, arguments)
    if target:
        entry["target"] = target[:80]
    if tool_name not in SENSITIVE_TOOLS and isinstance(result, str):
        summary = " ".join(result.split())[:MAX_ACTION_CHARS]
        if summary:
            entry["summary"] = summary
    actions.append(entry)
    del actions[:-max(1, int(limit))]
    return state


def activity_context(state: dict, limit: int = 6) -> str:
    """A short system note listing recent tool calls and how they turned out."""
    actions = [a for a in state.get("actions", []) if isinstance(a, dict)]
    if not actions:
        return ""
    lines = []
    for action in actions[-limit:]:
        desc = str(action.get("tool", "?"))
        if action.get("target"):
            desc += f"({action['target']})"
        status = action.get("status", "ok")
        line = f"- {desc}: {status}"
        if action.get("summary"):
            line += f" - {action['summary']}"
        lines.append(line)
    return (
        "Recent actions you already performed in this conversation (oldest first). "
        "Use them so follow-ups like 'close it' or 'do that again' stay truthful, "
        "and do not repeat an action that already succeeded:\n" + "\n".join(lines)
    )


def _action_target(tool: str, arguments: object) -> str:
    if not isinstance(arguments, dict):
        return ""
    for key in ("app", "game", "query", "key", "address", "pane_id"):
        value = arguments.get(key)
        if isinstance(value, str):
            # Collapse all whitespace (newlines, tabs, runs) into single spaces so
            # a target can never inject an extra line into the Recent-actions note.
            collapsed = " ".join(value.split())
            if collapsed:
                return collapsed
    return ""


#: Structured ``run_shell`` result: "exit <code>: <output>".
_EXIT_STATUS_RE = re.compile(r"^exit\s+(-?\d+):")


def _classify(result: object) -> str:
    """Classify a tool result for the persisted action log.

    Deterministic and independent of the model. The ``run_shell`` result carries
    the exit code ("exit 0: ...", "exit 1: ..."), which is parsed directly rather
    than inferred from the absence of a known failure string; a timeout is a
    failure. Denials and ambiguity keep their markers.
    """
    if not isinstance(result, str):
        return "ok"
    text = result.strip()
    if not text:
        return "ok"
    # A structured exit status is authoritative (checked before the "error"
    # prefix so e.g. "exit 0: error: ..." from command output stays "ok").
    match = _EXIT_STATUS_RE.match(text)
    if match:
        return "ok" if int(match.group(1)) == 0 else "failed"
    if text.startswith("error"):
        return "failed"
    lowered = text.lower()
    if "ambiguous" in lowered[:24]:
        return "ambiguous"
    if "denied" in lowered:
        return "denied"
    if lowered.startswith("command timed out"):
        return "failed"
    return "ok"


def clear(cfg: dict) -> None:
    save(cfg, new_state())
