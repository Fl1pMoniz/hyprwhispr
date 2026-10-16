"""Tests for scripts/download-models.sh integrity behaviour.

They copy a small fake "model" over a file:// URL, so no network or real model
weights are involved. Skipped when the shell tools are unavailable.
"""

import hashlib
import os
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "download-models.sh"

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("sha256sum") and shutil.which("curl")),
    reason="needs bash, curl and sha256sum",
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(tmp_path, url, sha, name="ggml-small.bin"):
    data = tmp_path / "data"
    env = {
        **os.environ,
        "HYPRWHISPR_DATA": str(data),
        "WHISPER_MODEL_NAME": name,
        "WHISPER_MODEL_URL": url,
        "WHISPER_MODEL_SHA256": sha,
    }
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    return result, data / "models" / name


def test_download_verifies_then_installs(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"pretend-model-bytes" * 500)
    result, final = _run(tmp_path, source.as_uri(), _sha(source))
    assert result.returncode == 0, result.stderr
    assert final.exists() and _sha(final) == _sha(source)
    assert not final.with_name(final.name + ".part").exists()


def test_download_rejects_checksum_mismatch(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"real-bytes")
    result, final = _run(tmp_path, source.as_uri(), "0" * 64)
    assert result.returncode != 0
    assert "mismatch" in (result.stderr + result.stdout).lower()
    assert not final.exists()  # nothing installed
    assert not final.with_name(final.name + ".part").exists()  # partial removed


def test_existing_verified_model_is_kept(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"already-here")
    # first run installs it
    _run(tmp_path, source.as_uri(), _sha(source))
    # second run should be a no-op success
    result, final = _run(tmp_path, source.as_uri(), _sha(source))
    assert result.returncode == 0
    assert "already present" in (result.stdout + result.stderr)


def test_interrupted_download_leaves_no_partial(tmp_path):
    # A source that cannot be fetched must fail and leave no .part behind.
    missing = (tmp_path / "does-not-exist.bin").as_uri()
    result, final = _run(tmp_path, missing, "0" * 64)
    assert result.returncode != 0
    assert not final.exists()
    assert not final.with_name(final.name + ".part").exists()
