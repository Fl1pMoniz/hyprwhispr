"""High-impact actions. Every one of these asks for explicit confirmation
through :mod:`hyprwhispr.permissions` before it does anything, and every
attempt (approved or denied) is written to the local audit log.

These are intentionally narrow:

* ``run_shell``        run one command the user approved
* ``install_package``  open a terminal so the user can install a distro package
* ``delete_path``      move a file/folder to the trash (reversible)
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

from .notify import log_event
from .permissions import confirm
from .validation import args_ok, valid_package


def tool_run_shell(cfg: dict, command: str) -> str:
    if not args_ok(command, 2000):
        return "error: invalid command"
    if not confirm("Run this shell command?", command):
        log_event({"event": "tool_denied", "tool": "run_shell", "command": command})
        return "user denied the shell command"
    log_event({"event": "tool_approved", "tool": "run_shell", "command": command})
    try:
        # shell=True is deliberate and unique to this tool: the user explicitly
        # approved an arbitrary command (pipes, redirection). Every other tool
        # uses an argument vector instead of a shell string.
        result = subprocess.run(command, shell=True, capture_output=True, text=True,
                                timeout=int(cfg.get("tool_timeout", 60)))
    except subprocess.TimeoutExpired:
        return "command timed out"
    output = (result.stdout + result.stderr).strip()[:2000]
    return f"exit {result.returncode}: {output or '(no output)'}"


def tool_install_package(cfg: dict, package: str) -> str:
    if not valid_package(package):
        return "error: invalid package name"
    if not confirm("Install this package with your package manager?", package):
        log_event({"event": "tool_denied", "tool": "install_package", "package": package})
        return "user denied the package installation"
    log_event({"event": "tool_approved", "tool": "install_package", "package": package})
    terminal = shutil.which(cfg["terminal_bin"]) or "kitty"
    # The command is a fixed vector plus a validated name; the user types their
    # own password in the terminal, hyprwhispr never handles it.
    subprocess.Popen(
        [terminal, "-T", "Install package", "-e", "sudo", "dnf", "install", "-y", package],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return f"opened a terminal to install '{package}' (you will be asked for your password)"


def tool_delete_path(cfg: dict, path: str) -> str:
    if not args_ok(path, 1000):
        return "error: invalid path"
    target = pathlib.Path(os.path.expanduser(path)).resolve()
    if not target.exists():
        return f"error: {target} does not exist"
    if not confirm("Move this to the trash?", str(target)):
        log_event({"event": "tool_denied", "tool": "delete_path", "path": str(target)})
        return "user denied the deletion"
    log_event({"event": "tool_approved", "tool": "delete_path", "path": str(target)})
    if not shutil.which("gio"):
        return "error: gio not available for safe trash"
    returncode = subprocess.run(["gio", "trash", str(target)], check=False).returncode
    return f"moved to trash: {target}" if returncode == 0 else "error: could not move to trash"
