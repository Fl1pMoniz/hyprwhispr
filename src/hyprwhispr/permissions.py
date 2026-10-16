"""Confirmation gate for high-impact actions.

Every tool that changes state on the user's system (shell, package install,
file deletion, killing a process) calls :func:`confirm` first. The prompt is a
native dialog (``zenity`` preferred, ``rofi`` as a fallback) and it **fails
closed**: if no dialog is available, or the user does not answer within the
timeout, the action is denied.
"""

from __future__ import annotations

import shutil
import subprocess

from .notify import notify

#: Unanswered prompts auto-deny after this many seconds.
CONFIRM_TIMEOUT_SECONDS = 60


def confirm(action: str, detail: str = "") -> bool:
    """Return True only if the user explicitly approves ``action``."""
    text = f"{action}\n\n{detail}" if detail else action

    if shutil.which("zenity"):
        try:
            result = subprocess.run(
                [
                    "zenity", "--question",
                    "--title", "hyprwhispr - confirm",
                    "--width", "480",
                    "--text", text,
                    "--ok-label", "Allow", "--cancel-label", "Deny",
                    f"--timeout={CONFIRM_TIMEOUT_SECONDS}",
                ],
                check=False,
            )
            return result.returncode == 0
        except OSError:
            pass

    if shutil.which("rofi"):
        try:
            result = subprocess.run(
                ["rofi", "-dmenu", "-p", "Allow?", "-mesg", text],
                input="Deny\nAllow\n", text=True, capture_output=True, check=False,
            )
            return "Allow" in (result.stdout or "")
        except OSError:
            pass

    notify("Action blocked", f"No confirmation dialog available; denied: {action}", "critical")
    return False
