"""Tests for scripts/verify.sh config-awareness.

These run the read-only script against a temporary config/data dir and a mocked
PATH; they never install anything. The key regression: verification must respect
the *configured* whisper_bin instead of only the default data-dir path.
"""

import json
import os
import shutil
import stat
import subprocess
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify.sh"

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="verify tests need bash")
BASH = shutil.which("bash") or "bash"


def _exec(path, body="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _env(tmp_path, config, data):
    env = dict(os.environ)
    env.update({
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "home" / ".config"),
        "XDG_DATA_HOME": str(tmp_path / "home" / ".local" / "share"),
        "HYPRWHISPR_CONFIG": str(config),
        "HYPRWHISPR_DATA": str(data),
        "NO_COLOR": "1",
    })
    return env


def _run(tmp_path, config, data, path=None):
    env = _env(tmp_path, config, data)
    if path is not None:
        env["PATH"] = path
    return subprocess.run([BASH, str(SCRIPT)], env=env, capture_output=True, text=True)


def test_verify_respects_configured_whisper_bin(tmp_path):
    data = tmp_path / "data"
    (data / "models").mkdir(parents=True)
    (data / "models" / "ggml-small.bin").write_bytes(b"model")
    wb = _exec(tmp_path / "custom" / "whisper-cli")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"whisper_bin": str(wb), "whisper_model": str(data / "models" / "ggml-small.bin")}))

    result = _run(tmp_path, config, data)
    assert f"[ok]   whisper binary: {wb}" in result.stdout
    assert "whisper binary not executable" not in result.stdout


def test_verify_finds_whisper_cli_on_path(tmp_path):
    data = tmp_path / "data"
    (data / "models").mkdir(parents=True)
    (data / "models" / "ggml-small.bin").write_bytes(b"model")
    bindir = tmp_path / "bin"
    _exec(bindir / "whisper-cli")
    config = tmp_path / "config.json"
    # empty whisper_bin -> should fall back to a PATH lookup
    config.write_text(json.dumps({"whisper_bin": "", "whisper_model": str(data / "models" / "ggml-small.bin")}))

    result = _run(tmp_path, config, data, path=f"{bindir}:{os.environ['PATH']}")
    assert "whisper-cli on PATH" in result.stdout
    assert "whisper binary not executable" not in result.stdout


def test_verify_reports_missing_configured_whisper_bin(tmp_path):
    data = tmp_path / "data"
    (data / "models").mkdir(parents=True)
    (data / "models" / "ggml-small.bin").write_bytes(b"model")
    missing = tmp_path / "nope" / "whisper-cli"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"whisper_bin": str(missing), "whisper_model": str(data / "models" / "ggml-small.bin")}))

    # PATH without whisper-cli so only the configured (missing) path is relevant
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("python3", "bash", "notify-send", "ollama", "curl", "cat", "grep", "command"):
        real = shutil.which(tool)
        if real:
            (bindir / tool).symlink_to(real)
    result = _run(tmp_path, config, data, path=str(bindir))
    assert "whisper binary not executable" in result.stdout
    assert str(missing) in result.stdout
