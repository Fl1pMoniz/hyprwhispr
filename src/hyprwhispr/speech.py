"""Local English speech-to-text using whisper.cpp.

whisper.cpp is a native binary (built by ``scripts/setup-whisper.sh``) that reads
a WAV file and writes a ``.txt`` transcript. It runs fully offline. Set
``whisper_gpu`` to false to use the CPU instead of CUDA.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

from . import config


def transcribe(cfg: dict, wav_path: str | pathlib.Path) -> tuple[str, str | None]:
    """Return ``(text, error)``. ``error`` is None on success."""
    wav_path = pathlib.Path(wav_path)
    if not pathlib.Path(cfg["whisper_bin"]).exists():
        return "", f"whisper binary not found at {cfg['whisper_bin']} (run scripts/setup-whisper.sh)"
    if not pathlib.Path(cfg["whisper_model"]).exists():
        return "", f"whisper model not found at {cfg['whisper_model']} (run scripts/download-models.sh)"

    out_prefix = config.RUNTIME_DIR / "transcript"
    cmd = [
        cfg["whisper_bin"], "-m", cfg["whisper_model"], "-f", str(wav_path),
        "-l", cfg["language"], "-nt", "-otxt", "-of", str(out_prefix),
    ]
    if not cfg.get("whisper_gpu", True):
        cmd.append("-ng")  # --no-gpu
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return "", "transcription timed out"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace")[:200]
        return "", f"whisper failed: {detail}"

    txt_file = out_prefix.with_suffix(".txt")
    if not txt_file.exists():
        return "", "no transcript produced"
    text = txt_file.read_text().strip()
    text = re.sub(r"\[[^\]]*\]", " ", text)  # drop [BLANK_AUDIO] / [MUSIC] markers
    return re.sub(r"\s+", " ", text).strip(), None
