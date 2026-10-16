"""Local English speech-to-text using whisper.cpp.

whisper.cpp is a native binary (built by ``scripts/setup-whisper.sh``) that reads
a WAV file and writes a ``.txt`` transcript. It runs fully offline. Set
``whisper_gpu`` to false to use the CPU instead of CUDA; if a GPU run fails, we
automatically retry on the CPU so a driver hiccup does not lose the request.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

from . import config

_GPU_ERROR_MARKERS = ("cuda", "cublas", "cudart", "ggml_cuda", "no cuda-capable", "out of memory")


def clean_transcript(text: str) -> str:
    """Drop whisper markers and collapse immediate word repetitions."""
    text = re.sub(r"\[[^\]]*\]", " ", text)  # [BLANK_AUDIO] / [MUSIC]
    text = re.sub(r"\b(\w+)(?:[\s,]+\1\b)+", r"\1", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _run_whisper(cfg: dict, wav_path: pathlib.Path, out_prefix: pathlib.Path, use_gpu: bool, timeout: int):
    cmd = [
        cfg["whisper_bin"], "-m", cfg["whisper_model"], "-f", str(wav_path),
        "-l", cfg["language"], "-nt", "-otxt", "-of", str(out_prefix),
    ]
    if not use_gpu:
        cmd.append("-ng")  # --no-gpu
    return subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)


def _gpu_failure(exc: subprocess.CalledProcessError) -> bool:
    detail = (exc.stderr or b"").decode(errors="replace").lower()
    return any(marker in detail for marker in _GPU_ERROR_MARKERS)


def transcribe(cfg: dict, wav_path: str | pathlib.Path) -> tuple[str, str | None]:
    """Return ``(text, error)``. ``error`` is None on success."""
    wav_path = pathlib.Path(wav_path)
    if not pathlib.Path(cfg["whisper_bin"]).exists():
        return "", f"whisper binary not found at {cfg['whisper_bin']} (run scripts/setup-whisper.sh)"
    if not pathlib.Path(cfg["whisper_model"]).exists():
        return "", f"whisper model not found at {cfg['whisper_model']} (run scripts/download-models.sh)"

    out_prefix = config.RUNTIME_DIR / "transcript"
    timeout = int(cfg.get("whisper_timeout", 120))
    use_gpu = bool(cfg.get("whisper_gpu", True))

    try:
        _run_whisper(cfg, wav_path, out_prefix, use_gpu, timeout)
    except subprocess.TimeoutExpired:
        return "", "transcription timed out"
    except subprocess.CalledProcessError as exc:
        if use_gpu and _gpu_failure(exc):  # GPU failed: fall back to CPU once
            try:
                _run_whisper(cfg, wav_path, out_prefix, False, timeout)
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as retry:
                return "", _describe_failure(retry)
        else:
            return "", _describe_failure(exc)

    txt_file = out_prefix.with_suffix(".txt")
    try:
        text = txt_file.read_text().strip()
    except OSError:
        return "", "no transcript produced"
    finally:
        _cleanup(out_prefix)
    return clean_transcript(text), None


def _describe_failure(exc: Exception) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return "transcription timed out"
    detail = ""
    if isinstance(exc, subprocess.CalledProcessError):
        detail = (exc.stderr or b"").decode(errors="replace")[:200]
    return f"whisper failed: {detail}"


def _cleanup(out_prefix: pathlib.Path) -> None:
    for suffix in (".txt", ".json", ".vtt", ".srt", ".csv"):
        out_prefix.with_suffix(suffix).unlink(missing_ok=True)
