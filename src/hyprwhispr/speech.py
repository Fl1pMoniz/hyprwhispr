"""Local multilingual speech-to-text using whisper.cpp.

whisper.cpp is a native binary (built by ``scripts/setup-whisper.sh``) that reads
a WAV file and writes a ``.txt`` transcript. It runs fully offline.

The default model is the multilingual ``ggml-small.bin`` and the default language
setting is automatic detection (``-l auto``) using whisper's built-in language
detector. The transcript is produced in the spoken language — this is
transcription, never translation. Set ``whisper_gpu`` to false to use the CPU
instead of CUDA; if a GPU run fails, we automatically retry on the CPU.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

from . import config
from .notify import log_event

_GPU_ERROR_MARKERS = ("cuda", "cublas", "cudart", "ggml_cuda", "no cuda-capable", "out of memory")

#: Value passed to whisper.cpp ``-l`` to auto-detect the spoken language.
LANGUAGE_AUTO = "auto"

#: Shape of a whisper language code (ISO-639-ish short code). This is a *format*
#: check only; whisper owns the real list of supported languages, so any valid
#: short code is passed straight through without an application-side allow-list.
_LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}$")


def clean_transcript(text: str) -> str:
    """Drop whisper markers and collapse immediate word repetitions."""
    text = re.sub(r"\[[^\]]*\]", " ", text)  # [BLANK_AUDIO] / [MUSIC]
    text = re.sub(r"\b(\w+)(?:[\s,]+\1\b)+", r"\1", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def resolve_language(value: object) -> tuple[str | None, str | None]:
    """Map a config ``language`` value to a whisper ``-l`` argument.

    Returns ``(language_arg, error)``:

    * ``None`` / ``""`` / ``"auto"`` -> ``("auto", None)`` (detect the language)
    * a short ISO-639 code such as ``"en"`` or ``"pt"`` -> that code
    * anything else -> ``(None, <message>)`` so the caller can report it
    """
    if value is None:
        return LANGUAGE_AUTO, None
    if not isinstance(value, str):
        return None, (f"invalid language {value!r}: use a short code like 'en' or 'pt', "
                      "or null for automatic detection")
    code = value.strip().lower()
    if code in ("", LANGUAGE_AUTO):
        return LANGUAGE_AUTO, None
    if _LANGUAGE_CODE_RE.match(code):
        return code, None
    return None, (f"invalid language {value!r}: use a short code like 'en' or 'pt', "
                  "or null for automatic detection")


def _looks_english_only(model_path: str) -> bool:
    return str(model_path).endswith(".en.bin")


def build_command(cfg: dict, wav_path, out_prefix, use_gpu: bool, language: str | None = None) -> list[str]:
    """Build the whisper.cpp argv. Pure, so it can be asserted in tests.

    Never adds ``-tr``/``--translate``: output stays in the spoken language.
    """
    if language is None:
        language, _ = resolve_language(cfg.get("language"))
    cmd = [
        cfg["whisper_bin"], "-m", cfg["whisper_model"], "-f", str(wav_path),
        "-l", language or LANGUAGE_AUTO, "-nt", "-otxt", "-of", str(out_prefix),
    ]
    if not use_gpu:
        cmd.append("-ng")  # --no-gpu
    return cmd


def _run_whisper(cfg: dict, wav_path: pathlib.Path, out_prefix: pathlib.Path, use_gpu: bool, timeout: int):
    cmd = build_command(cfg, wav_path, out_prefix, use_gpu)
    return subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)


def _gpu_failure(exc: subprocess.CalledProcessError) -> bool:
    detail = (exc.stderr or b"").decode(errors="replace").lower()
    return any(marker in detail for marker in _GPU_ERROR_MARKERS)


def transcribe(cfg: dict, wav_path: str | pathlib.Path) -> tuple[str, str | None]:
    """Return ``(text, error)``. ``error`` is None on success.

    The transcript keeps the spoken language; whisper's auto-detection picks it
    when ``language`` is unset.
    """
    wav_path = pathlib.Path(wav_path)
    if not pathlib.Path(cfg["whisper_bin"]).exists():
        return "", f"whisper binary not found at {cfg['whisper_bin']} (run scripts/setup-whisper.sh)"
    if not pathlib.Path(cfg["whisper_model"]).exists():
        return "", f"whisper model not found at {cfg['whisper_model']} (run scripts/download-models.sh)"

    language, language_error = resolve_language(cfg.get("language"))
    if language_error:
        return "", language_error
    if language == LANGUAGE_AUTO and _looks_english_only(cfg["whisper_model"]):
        # The .en models cannot detect other languages; warn but continue.
        log_event({"event": "language_warning", "reason": "english_only_model_with_auto_detect",
                   "model": pathlib.Path(cfg["whisper_model"]).name})

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
