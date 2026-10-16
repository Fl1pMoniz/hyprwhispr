"""Central tool-execution policy (Stage 6).

The LLM chooses tools; this layer is the Python-side authority that decides
whether a chosen call is allowed to run *at all*, before the tool body executes.
It is deliberately small and data-driven so every registered tool has an explicit
category and any capability gate is declared in one place.

Categories
----------

* ``read``        - observes state only; never confirms, never mutates.
* ``reversible``  - low-impact, non-destructive (open app, web search, notes).
* ``confirmed``   - changes state (closes/stops/opens a target, installs, deletes);
  the tool itself must show the exact target and call ``permissions.confirm``.

Capability gates bind a tool to a boolean config switch so a risky capability can
be turned off independently (e.g. arbitrary shell execution).

This module never executes anything: it returns ``(ok, error)``.
"""

from __future__ import annotations

READ = "read"
REVERSIBLE = "reversible"
CONFIRMED = "confirmed"

#: Every registered tool must appear here (a test enforces this).
TOOL_KINDS = {
    # applications / web / notes
    "open_app": REVERSIBLE,
    "list_apps": READ,
    "launch_steam_game": REVERSIBLE,
    "list_steam_games": READ,
    "close_app": CONFIRMED,
    "launch_opencode": REVERSIBLE,
    "web_search": REVERSIBLE,
    "save_note": REVERSIBLE,
    "list_notes": READ,
    "remember": REVERSIBLE,
    "recall": READ,
    # desktop windows / tmux
    "list_windows": READ,
    "close_window": CONFIRMED,
    "list_tmux_panes": READ,
    "close_tmux_pane": CONFIRMED,
    # selection / documents
    "get_selection": READ,
    "read_document": READ,
    "open_selected": CONFIRMED,
    # processes
    "list_processes": READ,
    "inspect_process": READ,
    "list_listening_ports": READ,
    "inspect_project_services": READ,
    "capture_tmux_pane": READ,
    "stop_process": CONFIRMED,
    # registered services
    "list_services": READ,
    "inspect_service": READ,
    "service_logs": READ,
    "start_service": CONFIRMED,
    "stop_service": CONFIRMED,
    "restart_service": CONFIRMED,
    # high-impact / command execution
    "run_shell": CONFIRMED,
    "install_package": CONFIRMED,
    "delete_path": CONFIRMED,
}

#: Tools gated by a boolean config capability (default in config.DEFAULTS).
CAPABILITY_GATES = {
    "run_shell": "shell_control",
    "stop_process": "process_control",
    "start_service": "service_lifecycle",
    "stop_service": "service_lifecycle",
    "restart_service": "service_lifecycle",
    "read_document": "document_read",
}

_CAPABILITY_MESSAGES = {
    "shell_control": ("arbitrary shell execution is disabled; set \"shell_control\": true to "
                      "allow it. Registered services should use start_service/restart_service "
                      "instead of a shell command"),
    "process_control": "process control is disabled; set \"process_control\": true to allow it",
    "service_lifecycle": ("service lifecycle management is disabled; set \"service_lifecycle\": "
                          "true to allow it"),
    "document_read": "reading document contents is disabled; set \"document_read\": true to allow it",
}

_MAX_ARG = 4000


def capability_error(gate: str) -> str:
    return f"error: {_CAPABILITY_MESSAGES.get(gate, 'this action is disabled')}"


def authorize(cfg: dict, name: str, arguments: object, required) -> tuple[bool, str | None]:
    """Validate a tool call against the policy. Returns ``(ok, error)``.

    Checks, in order: the tool is known and categorized; its capability gate (if
    any) is enabled in the config; the arguments are a mapping; and every required
    argument is a non-empty bounded string. This is the single execution boundary
    for authorization - the model's own wording is never trusted here.
    """
    if name not in TOOL_KINDS:
        return False, f"error: tool '{name}' is not authorized"
    gate = CAPABILITY_GATES.get(name)
    if gate and not bool(cfg.get(gate, False)):
        return False, capability_error(gate)
    if not isinstance(arguments, dict):
        return False, f"error: arguments for '{name}' must be a JSON object"
    for key in required:
        value = arguments.get(key, "")
        if not isinstance(value, str) or not value.strip():
            return False, f"error: '{name}' requires a non-empty '{key}'"
        if len(value) > _MAX_ARG:
            return False, f"error: '{name}' argument '{key}' is too long"
    return True, None
