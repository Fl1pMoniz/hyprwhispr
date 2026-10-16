"""Shared pytest setup.

Runs the whole suite against an isolated data/config/runtime directory so tests
never touch the user's real installation, models, notes or logs. The environment
must be set *before* ``hyprwhispr`` is imported, because the paths are computed
at import time.
"""

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="hyprwhispr-tests-"))
os.environ.setdefault("HYPRWHISPR_DATA", str(_TMP / "data"))
os.environ.setdefault("HYPRWHISPR_CONFIG", str(_TMP / "config.json"))
os.environ.setdefault("HYPRWHISPR_RUNTIME", str(_TMP / "run"))
