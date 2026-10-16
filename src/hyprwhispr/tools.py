"""Tool registry and JSON schemas for the model.

The model chooses tools from a structured JSON schema (function calling), not by
matching natural-language text with regexes. ``dispatch_tool`` validates the
name, fills only the declared parameters with defaults, logs the call, and
catches exceptions so a single bad call can never crash a turn.
"""

from __future__ import annotations

from . import apps, memory, system_actions, web
from .notify import log_event

# name -> (callable, [parameter names])
TOOL_IMPL = {
    "open_app": (apps.tool_open_app, ["app"]),
    "list_apps": (apps.tool_list_apps, ["query"]),
    "launch_steam_game": (apps.tool_launch_steam_game, ["game"]),
    "list_steam_games": (apps.tool_list_steam_games, ["query"]),
    "close_app": (apps.tool_close_app, ["app"]),
    "launch_opencode": (apps.tool_launch_opencode, ["prompt"]),
    "web_search": (web.tool_web_search, ["query"]),
    "save_note": (memory.tool_save_note, ["text"]),
    "list_notes": (memory.tool_list_notes, ["query"]),
    "remember": (memory.tool_remember, ["key", "value"]),
    "recall": (memory.tool_recall, ["key"]),
    "run_shell": (system_actions.tool_run_shell, ["command"]),
    "install_package": (system_actions.tool_install_package, ["package"]),
    "delete_path": (system_actions.tool_delete_path, ["path"]),
}

TOOLS_SCHEMA = [
    {"type": "function", "function": {
        "name": "open_app",
        "description": (
            "Open any installed desktop application by name, or launch an installed "
            "Steam game by name. Matches every installed .desktop app (browser, "
            "terminal, editors, flatpaks, ...) and the Steam library. Use for "
            "'open X', 'launch X' or 'play X'."
        ),
        "parameters": {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]}}},
    {"type": "function", "function": {
        "name": "list_apps",
        "description": (
            "List installed desktop applications. The query is an OPTIONAL name "
            "filter; leave it empty to list apps. Do not put filler words like "
            "'installed', 'some' or 'three' in the query."
        ),
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "launch_steam_game",
        "description": "Launch an installed Steam game by name.",
        "parameters": {"type": "object", "properties": {"game": {"type": "string"}}, "required": ["game"]}}},
    {"type": "function", "function": {
        "name": "list_steam_games",
        "description": (
            "List installed Steam games. The query is an OPTIONAL name filter; leave "
            "it empty to list all games. Do not put filler words like 'installed', "
            "'some' or 'three' in the query."
        ),
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "close_app",
        "description": (
            "Close an open application or quit a running Steam game by name. Closes "
            "its windows gracefully; only kills a process after you approve."
        ),
        "parameters": {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]}}},
    {"type": "function", "function": {
        "name": "launch_opencode",
        "description": (
            "Open the OpenCode coding agent in a new terminal. Optionally prepare "
            "(copy to clipboard and save) a coding prompt."
        ),
        "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": (
            "Open a web search in the user's browser. The query leaves this machine; "
            "no page content is read back."
        ),
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "save_note",
        "description": "Save a note locally to the user's notes file.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "list_notes",
        "description": "Search the user's saved notes.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "Persist a preference or fact about the user across sessions.",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                       "required": ["key", "value"]}}},
    {"type": "function", "function": {
        "name": "recall",
        "description": (
            "Look up what the user previously asked you to remember. For 'what did I "
            "ask you to remember' or 'what do you know about me', call it with no key "
            "to list everything. Provide a key only when looking up one specific fact."
        ),
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "DESTRUCTIVE: run an arbitrary shell command. Always requires explicit user confirmation.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "install_package",
        "description": "DESTRUCTIVE: install a system package. Always requires explicit user confirmation.",
        "parameters": {"type": "object", "properties": {"package": {"type": "string"}}, "required": ["package"]}}},
    {"type": "function", "function": {
        "name": "delete_path",
        "description": "DESTRUCTIVE: move a file or folder to the trash. Always requires explicit user confirmation.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]


def dispatch_tool(cfg: dict, name: str, arguments: dict) -> str:
    """Run the named tool with only its declared parameters; never raise."""
    import time

    entry = TOOL_IMPL.get(name)
    if not entry:
        log_event({"event": "tool_call", "tool": name, "status": "unknown_tool"})
        return f"error: unknown tool '{name}'"
    if not isinstance(arguments, dict):
        log_event({"event": "tool_call", "tool": name, "status": "bad_arguments"})
        return f"error: arguments for '{name}' must be a JSON object"

    func, parameters = entry
    kwargs = {param: arguments.get(param, "") for param in parameters}
    record = {"event": "tool_call", "tool": name}
    if cfg.get("log_tool_args"):
        record["args"] = kwargs
    start = time.perf_counter()
    try:
        result = func(cfg, **kwargs)
    except Exception as exc:  # noqa: BLE001 - a tool must never crash the turn
        record.update(status="exception", error=type(exc).__name__, ms=round((time.perf_counter() - start) * 1000))
        log_event(record)
        return f"error running {name}: {exc}"
    record["ms"] = round((time.perf_counter() - start) * 1000)
    record["status"] = _classify(result)
    log_event(record)
    return result


def _classify(result: str) -> str:
    if isinstance(result, str) and result.startswith("error"):
        return "error"
    if isinstance(result, str) and "ambiguous" in result[:20]:
        return "ambiguous"
    if isinstance(result, str) and ("denied" in result):
        return "denied"
    return "ok"
