"""Executable discovery: decide *whether* a program exists before running it.

Discovery answers one question only - "is there a usable executable for this
capability?" - and returns a structured :class:`Resolution`. It never grants
permission to run anything: finding a program and being authorised to run it are
two separate checks, and the caller still goes through the normal tool path (and
any confirmation gate).

Lookups are intentionally cheap and bounded:

* an explicit user-configured value is tried first (absolute path validated, or a
  name looked up on ``PATH``);
* then a small, ordered list of legitimate executable names for the capability.

Path lookups do not scan the filesystem. A short-lived in-process cache avoids
repeating the same lookup several times within one action; it is bounded and can
be cleared (see :func:`clear_cache`).
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time
from dataclasses import dataclass

#: How long a cached resolution stays valid (seconds).
CACHE_TTL_SECONDS = 30.0
_CACHE: dict[tuple, tuple[float, "Resolution"]] = {}


@dataclass(frozen=True)
class Resolution:
    """The outcome of a discovery attempt (never an authorisation to run)."""

    requested: str = ""          # the configured value, if the user set one
    program: str | None = None   # resolved executable path/name, or None
    source: str = "none"         # "configured" | "path" | "fallback" | "none"
    label: str = ""              # friendly name of the chosen program
    tried: tuple[str, ...] = ()  # every name/path attempted, in order

    @property
    def found(self) -> bool:
        return bool(self.program)

    @property
    def used_alternative(self) -> bool:
        """True when the preferred program was missing and another was chosen."""
        return self.found and bool(self.requested) and self.source in ("path", "fallback")


def clear_cache() -> None:
    """Forget cached resolutions (call after installing/removing software)."""
    _CACHE.clear()


def is_executable_file(path: object) -> bool:
    """True when *path* names an existing, executable regular file."""
    try:
        candidate = pathlib.Path(os.fspath(path))
    except TypeError:
        return False
    return candidate.is_file() and os.access(candidate, os.X_OK)


def _lookup(name: str) -> str | None:
    """Resolve one name: an explicit path is validated, a bare name uses PATH."""
    name = (name or "").strip()
    if not name:
        return None
    if os.sep in name:
        return name if is_executable_file(name) else None
    return shutil.which(name)


def resolve_program(candidates, configured: str = "", *, labels: dict | None = None,
                    fallback_names=(), use_cache: bool = True) -> Resolution:
    """Find a usable executable for a capability.

    ``candidates`` is an ordered iterable of executable names (most preferred
    first). ``configured`` is the user's explicit choice and is tried first; if it
    is set but unusable, the candidates are still searched so a sensible
    alternative can be used. Names in ``fallback_names`` are marked with
    ``source="fallback"`` (generic openers, not capability-specific programs).
    """
    candidates = tuple(c for c in candidates if c)
    configured = (configured or "").strip()
    labels = labels or {}
    fallback = set(fallback_names)

    key = (candidates, configured, tuple(sorted(fallback)))
    if use_cache:
        cached = _CACHE.get(key)
        if cached and (time.monotonic() - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

    tried: list[str] = []
    resolution: Resolution | None = None

    if configured:
        tried.append(configured)
        path = _lookup(configured)
        if path:
            resolution = Resolution(requested=configured, program=path, source="configured",
                                    label=labels.get(os.path.basename(configured), configured),
                                    tried=tuple(tried))

    if resolution is None:
        ordered = list(candidates) + [n for n in fallback_names if n not in candidates]
        for name in ordered:
            tried.append(name)
            path = _lookup(name)
            if path:
                resolution = Resolution(requested=configured, program=path,
                                        source="fallback" if name in fallback else "path",
                                        label=labels.get(name, name), tried=tuple(tried))
                break

    if resolution is None:
        resolution = Resolution(requested=configured, program=None, source="none",
                                tried=tuple(tried))

    if use_cache:
        _CACHE[key] = (time.monotonic(), resolution)
    return resolution
