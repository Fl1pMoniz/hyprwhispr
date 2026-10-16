"""User-facing notifications and the local audit log.

Notifications go through ``notify-send`` (swaync, dunst, mako, ... all speak
its interface). The audit log is a local JSON-lines file; it never leaves the
machine and never contains secrets.
"""

from __future__ import annotations

import json
import subprocess

from . import config


def log_event(fields: dict) -> None:
    """Append one JSON object to logs/audit.jsonl (best effort)."""
    config.ensure_dirs()
    record = {"ts": config.now(), **fields}
    try:
        with (config.LOGS_DIR / "audit.jsonl").open("a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def notify(title: str, body: str, urgency: str = "normal", timeout: int | None = None) -> None:
    """Show a desktop notification, or print to the terminal as a fallback."""
    config.ensure_dirs()
    cmd = ["notify-send", "-a", "hyprwhispr", "-u", urgency]
    if timeout:
        cmd += ["-t", str(timeout)]
    cmd += [title, body or ""]
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        print(f"[{title}] {body}")
