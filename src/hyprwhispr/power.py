"""Activation ("power") and safe model release for the one-shot assistant.

HyprWhispr is not a daemon: every normal request (push-to-talk, ``ask``,
``listen``, the wake-word worker) starts a process and exits. There is therefore
no long-lived process to start or stop. "Power" is a persistent **enabled flag**:

* ``on``  - assistant entry points are permitted (the model still loads only when
  the first real inference request needs it);
* ``off`` - new assistant requests and recordings are refused, and the configured
  Ollama model is released as soon as it is safe.

Disabling never stops the Ollama server and never touches other Ollama activity.
Unloading is a capability check only: it reports what Ollama's API confirms and
never claims VRAM was physically reclaimed.
"""

from __future__ import annotations

import os

from . import config, llm


class PoweredOff(RuntimeError):
    """Raised when an assistant request is made while hyprwhispr is disabled."""


def require_enabled(cfg: dict) -> None:
    """Refuse an assistant request when the assistant is disabled."""
    if not config.is_enabled(cfg):
        raise PoweredOff("hyprwhispr is off; enable it with 'hyprwhispr power on'")


def recording_active() -> bool:
    """Best-effort: is a push-to-talk recording in progress right now?

    Based on the recorder pidfile. It cannot see a detached inference worker, so
    it is a hint for safe unloading, not a cross-process guarantee.
    """
    try:
        pid = int(config.PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _base(name: str) -> str:
    return (name or "").split(":", 1)[0].strip().lower()


def model_loaded(cfg: dict, model: str) -> bool | None:
    """True/False when Ollama's ``/api/ps`` is reachable, else ``None`` (unknown)."""
    loaded = llm.loaded_models(cfg)
    if loaded is None:
        return None
    return any(_base(entry.get("name", "")) == _base(model) for entry in loaded)


def unload_if_idle(cfg: dict, model: str | None = None) -> tuple[bool, str]:
    """Release the configured model unless a recording is active.

    Returns ``(ok, message)``. ``ok`` is True only when the API-level unload was
    confirmed (or requested but unverifiable); it never implies VRAM was freed.
    """
    if recording_active():
        return False, "a recording is in progress; the model was left loaded until it finishes"
    model = model or cfg.get("model", "")
    if not model:
        return False, "no model is selected"
    ok, error = llm.unload_model(cfg, model)
    if not ok:
        return False, error or "unload failed"
    state = model_loaded(cfg, model)
    if state is None:
        return True, f"requested unload of '{model}'; the Ollama API could not be reached to confirm it"
    if state:
        return False, f"'{model}' is still loaded (Ollama may need a moment, or it was just used)"
    return True, f"unloaded '{model}' (API-level; VRAM reclamation is not measured here)"
