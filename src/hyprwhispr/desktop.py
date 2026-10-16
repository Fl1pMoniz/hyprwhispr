"""Verified desktop context and precisely-targeted desktop actions.

The model does the natural-language understanding; this module supplies *verified*
context and performs *validated* actions. It is read-only until a tool is asked to
act, and it never polls.

Identity rules:

* a Hyprland window ``address`` is the identity for window actions;
* a tmux ``pane_id`` (e.g. ``%3``) is the identity for pane actions;
* titles / classes / commands help the model interpret intent but are never the
  sole identity for a destructive action.

Focus is not selection: Hyprland reveals the focused *window*, not what is
selected *inside* it. When a selection (file, browser tab, editor document) cannot
be established reliably we say so instead of guessing.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

from .notify import log_event
from .permissions import confirm

_HYPRCTL_TIMEOUT = 5
_ADDRESS_RE = re.compile(r"^0x[0-9a-f]+$")
_PANE_ID_RE = re.compile(r"^%\d+$")

#: tmux -F format for one line per pane (tab-separated).
_PANE_FORMAT = "\t".join([
    "#{pane_id}", "#{session_name}", "#{window_index}", "#{pane_index}",
    "#{pane_active}", "#{window_active}", "#{pane_current_command}",
    "#{pane_title}", "#{pane_current_path}", "#{pane_tty}",
])
_CLIENT_FORMAT = "\t".join(["#{client_pid}", "#{client_tty}", "#{client_session}"])


# ---------------------------------------------------------------------------
# low-level, capability-gated access (never scans the whole filesystem)
# ---------------------------------------------------------------------------


def available() -> bool:
    """True when ``hyprctl`` is present (Hyprland integration usable)."""
    return shutil.which("hyprctl") is not None


def tmux_available() -> bool:
    """True when ``tmux`` is present."""
    return shutil.which("tmux") is not None


def _hyprctl_json(*args: str):
    if not available():
        return None
    try:
        proc = subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True,
                              check=False, timeout=_HYPRCTL_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _hyprctl_dispatch(expression: str) -> bool:
    if not available():
        return False
    try:
        proc = subprocess.run(["hyprctl", "dispatch", *expression.split(" ", 1)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False, timeout=_HYPRCTL_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def tmux_run(args: list[str]) -> tuple[bool, str]:
    """Run a tmux command. Returns ``(ok, stdout)``; ok is False when tmux is
    missing/unavailable or returns non-zero (e.g. no server running)."""
    if not tmux_available():
        return False, ""
    try:
        proc = subprocess.run(["tmux", *args], capture_output=True, text=True,
                              check=False, timeout=_HYPRCTL_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return proc.returncode == 0, proc.stdout


# ---------------------------------------------------------------------------
# windows
# ---------------------------------------------------------------------------


def _valid_address(address: object) -> bool:
    return isinstance(address, str) and bool(_ADDRESS_RE.match(address.strip().lower()))


def _normalize_window(raw: dict) -> dict:
    workspace = raw.get("workspace")
    return {
        "address": str(raw.get("address") or ""),
        "title": str(raw.get("title") or ""),
        "class": str(raw.get("class") or ""),
        "pid": raw.get("pid") if isinstance(raw.get("pid"), int) else None,
        "workspace": workspace.get("name") if isinstance(workspace, dict) else None,
    }


def focused_window() -> dict | None:
    """The focused Hyprland window, or None when unavailable/none."""
    raw = _hyprctl_json("activewindow")
    if not isinstance(raw, dict) or not raw.get("address"):
        return None
    return _normalize_window(raw)


def windows() -> list[dict]:
    """Every open window (normalized), or [] when unavailable."""
    raw = _hyprctl_json("clients")
    if not isinstance(raw, list):
        return []
    return [_normalize_window(w) for w in raw if isinstance(w, dict) and w.get("address")]


def window_by_address(address: str) -> dict | None:
    address = (address or "").strip().lower()
    if not _valid_address(address):
        return None
    for window in windows():
        if window["address"].lower() == address:
            return window
    return None


def window_line(window: dict, focused_address: str = "") -> str:
    marker = " [focused]" if window["address"].lower() == (focused_address or "").lower() else ""
    pid = f"  pid {window['pid']}" if window.get("pid") else ""
    return f"- {window['address']}  {window['class'] or '?'}  \"{window['title'][:80]}\"{marker}{pid}"


def context_line(cfg: dict) -> str:
    """A compact, verified note about the focused window for the model.

    Returns "" when desktop context is disabled or Hyprland is unavailable, so
    the model is never handed invented context.
    """
    if not cfg.get("desktop_context", True) or not available():
        return ""
    window = focused_window()
    if not window:
        return ("Desktop context: no focused Hyprland window could be read; you do not "
                "know which window the user means. Call list_windows or ask.")
    pid = f", pid {window['pid']}" if window.get("pid") else ""
    return (f"Desktop context (verified now): the focused window has address "
            f"{window['address']}, class '{window['class'] or '?'}', title "
            f"\"{window['title'][:80]}\"{pid}. Use this address only if the user clearly "
            "means the focused window; otherwise call list_windows. It may have changed "
            "by the time you act - close_window revalidates it.")


# ---------------------------------------------------------------------------
# processes (for terminal/tmux resolution; comm only, never full command lines)
# ---------------------------------------------------------------------------


def _process_table() -> dict[int, dict]:
    try:
        proc = subprocess.run(["ps", "-eo", "pid=,ppid=,comm="], capture_output=True,
                              text=True, check=False, timeout=_HYPRCTL_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return {}
    table: dict[int, dict] = {}
    for line in proc.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        table[pid] = {"ppid": ppid, "comm": parts[2].strip() if len(parts) > 2 else ""}
    return table


def _descendants(pid: int, table: dict[int, dict]) -> set[int]:
    children: dict[int, list[int]] = {}
    for child, info in table.items():
        children.setdefault(info["ppid"], []).append(child)
    found: set[int] = set()
    stack = [pid]
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


# ---------------------------------------------------------------------------
# tmux
# ---------------------------------------------------------------------------


def tmux_panes() -> list[dict] | None:
    """All tmux panes, or None when tmux/the server is unavailable."""
    ok, out = tmux_run(["list-panes", "-a", "-F", _PANE_FORMAT])
    if not ok:
        return None
    panes = []
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) < 10:
            continue
        panes.append({
            "pane_id": fields[0], "session": fields[1], "window_index": fields[2],
            "pane_index": fields[3], "active": fields[4] == "1",
            "window_active": fields[5] == "1", "command": fields[6], "title": fields[7],
            "cwd": fields[8], "tty": fields[9],
        })
    return panes


def _valid_pane_id(pane_id: object) -> bool:
    return isinstance(pane_id, str) and bool(_PANE_ID_RE.match(pane_id.strip()))


def focused_tmux_pane() -> dict:
    """Best-effort resolution of the pane shown in the focused terminal.

    Returns ``{"status": "ok", "pane": {...}}`` or a status of
    ``"unavailable" | "ambiguous" | "not_found"``. The assistant may be started
    from a global keybinding, so the process tree of the focused window - not the
    ``TMUX`` environment - is used to find the right client.
    """
    window = focused_window()
    if not window or not window.get("pid") or not tmux_available():
        return {"status": "unavailable"}
    table = _process_table()
    if not table:
        return {"status": "unavailable"}
    descendants = _descendants(int(window["pid"]), table)
    ok, out = tmux_run(["list-clients", "-F", _CLIENT_FORMAT])
    if not ok:
        return {"status": "unavailable"}
    clients = []
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        try:
            cpid = int(fields[0])
        except ValueError:
            continue
        if cpid in descendants:
            clients.append({"pid": cpid, "tty": fields[1], "session": fields[2]})
    if not clients:
        return {"status": "not_found"}
    if len(clients) > 1:
        return {"status": "ambiguous"}
    panes = tmux_panes() or []
    matching = [p for p in panes if p["tty"] == clients[0]["tty"]]
    if not matching:
        return {"status": "not_found"}
    if len(matching) > 1:
        return {"status": "ambiguous"}
    return {"status": "ok", "pane": matching[0]}


# ---------------------------------------------------------------------------
# tools exposed to the model
# ---------------------------------------------------------------------------


def tool_list_windows(cfg: dict, query: str = "") -> str:
    """Read-only: list open windows with the addresses the model can act on."""
    if not available():
        return "error: Hyprland (hyprctl) is not available; window control needs Hyprland"
    all_windows = windows()
    if not all_windows:
        return "no windows are open"
    focused = focused_window()
    focused_address = focused["address"] if focused else ""
    needle = (query or "").strip().lower()
    selected = [w for w in all_windows
                if not needle or needle in (w["class"] or "").lower() or needle in (w["title"] or "").lower()]
    if not selected:
        return f"no open window matches '{query}'"
    lines = [window_line(w, focused_address) for w in selected]
    return f"{len(selected)} of {len(all_windows)} window(s) (address, class, title):\n" + "\n".join(lines)


def tool_close_window(cfg: dict, address: str, reason: str = "") -> str:
    """Close exactly one window, identified by its Hyprland address."""
    address = (address or "").strip()
    if not _valid_address(address):
        return ("error: close_window needs a Hyprland window address (like 0x55f...); "
                "call list_windows first and use an address it returned")
    if not available():
        return "error: Hyprland (hyprctl) is not available; window control needs Hyprland"
    window = window_by_address(address)
    if not window:
        return f"error: no open window has address {address}; it may already be closed"
    detail = f"{window['title'] or '(untitled)'}\nclass: {window['class'] or '?'}"
    if window.get("pid"):
        detail += f"\npid: {window['pid']}"
    if reason:
        detail += f"\nreason: {reason}"
    detail += f"\naddress: {address}"
    if not confirm("Close this window?", detail):
        log_event({"event": "tool_denied", "tool": "close_window", "address": address})
        return "user denied closing the window"
    # Revalidate identity: the window may have closed or changed while the user
    # was deciding. Never substitute a different window.
    again = window_by_address(address)
    if not again:
        return "error: the window closed or changed before the action; nothing was done"
    if not _hyprctl_dispatch(f"closewindow address:{address}"):
        return f"error: Hyprland could not close the window {address}"
    log_event({"event": "close_window", "address": address, "class": again["class"]})
    return f"closed window: {again['title'] or again['class'] or address} ({again['class'] or '?'})"


def tool_list_tmux_panes(cfg: dict) -> str:
    """Read-only: list tmux panes and mark the pane of the focused terminal."""
    if not tmux_available():
        return "error: tmux is not installed"
    panes = tmux_panes()
    if panes is None:
        return "error: no tmux server is running (start a session first)"
    if not panes:
        return "no tmux panes are open"
    focused = focused_tmux_pane()
    focused_id = focused["pane"]["pane_id"] if focused.get("status") == "ok" else None
    lines = []
    for pane in panes:
        marker = " [focused]" if pane["pane_id"] == focused_id else ""
        lines.append(f"- {pane['pane_id']}  {pane['session']}:{pane['window_index']}.{pane['pane_index']}"
                     f"  {pane['command']}  cwd {pane['cwd']}  \"{pane['title'][:60]}\"{marker}")
    return f"{len(panes)} tmux pane(s) (pane id, session:window.pane, command, cwd):\n" + "\n".join(lines)


def tool_close_tmux_pane(cfg: dict, pane_id: str, reason: str = "") -> str:
    """Close exactly one tmux pane (never a whole session by name)."""
    pane_id = (pane_id or "").strip()
    if not _valid_pane_id(pane_id):
        return ("error: close_tmux_pane needs a tmux pane id like %3; "
                "call list_tmux_panes first and use an id it returned")
    if not tmux_available():
        return "error: tmux is not installed"
    panes = tmux_panes()
    if panes is None:
        return "error: no tmux server is running"
    target = next((p for p in panes if p["pane_id"] == pane_id), None)
    if not target:
        return f"error: no tmux pane {pane_id} (it may already be closed)"
    same_window = [p for p in panes if p["session"] == target["session"]
                   and p["window_index"] == target["window_index"]]
    same_session = [p for p in panes if p["session"] == target["session"]]
    impact = ""
    if len(same_window) == 1 and len(same_session) == 1:
        impact = "\nthis is the last pane: its window and session will end"
    elif len(same_window) == 1:
        impact = "\nthis is the last pane in its window"
    detail = (f"{target['session']}:{target['window_index']}.{target['pane_index']}  {target['command']}\n"
              f"cwd: {target['cwd']}\n\"{target['title'][:80]}\"\npane id: {pane_id}{impact}")
    if reason:
        detail += f"\nreason: {reason}"
    if not confirm("Close this tmux pane?", detail):
        log_event({"event": "tool_denied", "tool": "close_tmux_pane", "pane_id": pane_id})
        return "user denied closing the pane"
    again = next((p for p in (tmux_panes() or []) if p["pane_id"] == pane_id), None)
    if not again:
        return "error: the pane closed or changed before the action; nothing was done"
    ok, _ = tmux_run(["kill-pane", "-t", pane_id])
    if not ok:
        return f"error: tmux could not close pane {pane_id}"
    log_event({"event": "close_tmux_pane", "pane_id": pane_id})
    return (f"closed tmux pane {pane_id} "
            f"({again['session']}:{again['window_index']}.{again['pane_index']})")
