"""Small, explicit validators for tool arguments.

Keeping validation in one place makes the security review easy: every tool
checks the shape and length of its inputs before doing anything.
"""

from __future__ import annotations

import re

_PACKAGE_RE = re.compile(r"[A-Za-z0-9._+-]+")


def args_ok(value: object, maxlen: int = 4000) -> bool:
    """True when *value* is a string no longer than *maxlen*."""
    return isinstance(value, str) and len(value) <= maxlen


def non_empty(value: object, maxlen: int = 120) -> bool:
    return args_ok(value, maxlen) and bool(value.strip())


def valid_package(name: object) -> bool:
    """Restrict package names to characters that are safe on a command line."""
    return isinstance(name, str) and bool(_PACKAGE_RE.fullmatch(name))
