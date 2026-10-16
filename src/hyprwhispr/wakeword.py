"""Optional local wake-word activation (disabled by default).

Activation modes (``wake_word_mode``):

* ``shortcut``  - keyboard push-to-talk only (the default; unchanged behaviour)
* ``wake_word`` - wake word only
* ``both``      - keyboard shortcut *and* wake word
* ``disabled``  - no activation mechanism

Detection is delegated to a small, replaceable detector interface. Two engines
are available (``wake_word_engine``):

* ``whisper`` (the default via ``auto``) reuses the local whisper.cpp model and
  recognises any phrase in any language whisper supports - including the default
  Ukrainian ``дідько`` - with **no training**;
* ``openWakeWord`` (optional, lower CPU) recognises its English pre-trained
  phrases or a custom-trained model (its pre-trained models are
  CC-BY-NC-SA-4.0).

Without a usable engine, ``shortcut`` mode keeps working exactly as before.

All detection runs locally; no audio leaves the machine, no audio is written to
disk while waiting, and the LLM is never called until a command is captured.
"""

from __future__ import annotations

import array
import importlib.util
import math
import pathlib
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass, field

from . import audio, config, speech
from .notify import log_event, notify

#: Exact default wake word for new configurations (Ukrainian, preserved verbatim).
DEFAULT_WAKE_WORD = "дідько"

ACTIVATION_MODES = ("shortcut", "wake_word", "both", "disabled")
DEFAULT_MODE = "shortcut"
MAX_PHRASE_CHARS = 64

#: openWakeWord pre-trained model ids and the English phrases they detect.
PRETRAINED_MODELS = {
    "alexa": "alexa",
    "hey jarvis": "hey_jarvis",
    "hey mycroft": "hey_mycroft",
    "hey rhasspy": "hey_rhasspy",
    "what's the weather": "weather",
    "what is the weather": "weather",
}

INSTALL_HINT = (
    "install the optional engine with:  pipx inject hyprwhispr openwakeword sounddevice"
)


class WakeWordError(Exception):
    """Raised for configuration or engine problems with an actionable message."""


@dataclass
class WakeWordSettings:
    mode: str = DEFAULT_MODE
    phrase: str = DEFAULT_WAKE_WORD
    models: dict = field(default_factory=dict)
    threshold: float = 0.5
    cooldown: float = 2.0
    command_seconds: int = 6
    feedback: bool = True
    device: object = None
    engine: str = "auto"
    window_seconds: float = 2.5

    @property
    def enabled(self) -> bool:
        return self.mode in ("wake_word", "both")


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def validate_phrase(phrase: object) -> tuple[str | None, str | None]:
    """Return ``(clean_phrase, error)``. Trims surrounding whitespace only."""
    if not isinstance(phrase, str):
        return None, "the wake word must be text"
    clean = phrase.strip()
    if not clean:
        return None, "the wake word cannot be empty"
    if len(clean) > MAX_PHRASE_CHARS:
        return None, f"the wake word is too long (max {MAX_PHRASE_CHARS} characters)"
    if any(ord(ch) < 32 for ch in clean):
        return None, "the wake word cannot contain control characters"
    return clean, None


def validate_mode(mode: object) -> tuple[str | None, str | None]:
    if not isinstance(mode, str) or mode not in ACTIVATION_MODES:
        return None, f"invalid wake_word_mode {mode!r}; choose one of {', '.join(ACTIVATION_MODES)}"
    return mode, None


def get_settings(cfg: dict) -> WakeWordSettings:
    """Read wake-word settings from a config dict, applying safe defaults."""
    phrase = cfg.get("wake_word", DEFAULT_WAKE_WORD)
    if not isinstance(phrase, str):
        phrase = DEFAULT_WAKE_WORD
    models = cfg.get("wake_word_models") or {}
    if not isinstance(models, dict):
        models = {}
    try:
        threshold = float(cfg.get("wake_word_threshold", 0.5))
    except (TypeError, ValueError):
        threshold = 0.5
    try:
        cooldown = float(cfg.get("wake_word_cooldown_seconds", 2.0))
    except (TypeError, ValueError):
        cooldown = 2.0
    try:
        command_seconds = int(cfg.get("wake_word_command_seconds", 6))
    except (TypeError, ValueError):
        command_seconds = 6
    try:
        window_seconds = float(cfg.get("wake_word_window_seconds", 2.5))
    except (TypeError, ValueError):
        window_seconds = 2.5
    engine = str(cfg.get("wake_word_engine", "auto")).strip().lower()
    if engine not in ("auto", "whisper", "openwakeword"):
        engine = "auto"
    return WakeWordSettings(
        mode=str(cfg.get("wake_word_mode", DEFAULT_MODE)),
        phrase=phrase.strip(),
        models={str(k): str(v) for k, v in models.items()},
        threshold=min(max(threshold, 0.0), 1.0),
        cooldown=max(cooldown, 0.0),
        command_seconds=max(command_seconds, 1),
        feedback=bool(cfg.get("wake_word_feedback", True)),
        device=cfg.get("wake_word_device"),
        engine=engine,
        window_seconds=max(window_seconds, 0.5),
    )


def settings_error(cfg: dict) -> str | None:
    settings = get_settings(cfg)
    _, mode_error = validate_mode(settings.mode)
    if mode_error:
        return mode_error
    _, phrase_error = validate_phrase(settings.phrase)
    return phrase_error


def engine_available() -> bool:
    """True when the optional openWakeWord engine can be imported."""
    return importlib.util.find_spec("openwakeword") is not None


def _model_ref_exists(ref: str) -> bool:
    if ref in set(PRETRAINED_MODELS.values()):
        return True
    return pathlib.Path(ref).expanduser().exists()


def _whisper_available(cfg: dict) -> bool:
    bin_path = cfg.get("whisper_bin") or config.DEFAULTS["whisper_bin"]
    model_path = cfg.get("whisper_model") or config.DEFAULTS["whisper_model"]
    return pathlib.Path(bin_path).exists() and pathlib.Path(model_path).exists()


def select_engine(cfg: dict) -> str:
    """Resolve the detection backend: "whisper", "openwakeword" or "none".

    ``auto`` prefers an openWakeWord model that matches the phrase (lower CPU for
    its supported English phrases) and otherwise falls back to the local whisper
    engine, which works for any phrase in any language whisper supports.
    """
    engine = get_settings(cfg).engine
    if engine == "whisper":
        return "whisper" if _whisper_available(cfg) else "none"
    if engine == "openwakeword":
        return "openwakeword" if engine_available() else "none"
    if engine_available() and resolve_model(cfg, get_settings(cfg).phrase):
        return "openwakeword"
    if _whisper_available(cfg):
        return "whisper"
    if engine_available():
        return "openwakeword"
    return "none"


def _normalize_text(text: str) -> str:
    """Casefold, NFKC-normalise and drop punctuation (for matching only)."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def match_phrase(phrase: str, transcript: str) -> tuple[bool, str]:
    """Return ``(matched, remainder)`` for a wake phrase inside a transcript.

    Matching is done on normalised words (case/Unicode/punctuation-insensitive),
    but ``remainder`` keeps the original text of the transcript minus the matched
    phrase, so a one-stage utterance ("дідько, open Firefox") yields "open Firefox".
    """
    phrase_tokens = _normalize_text(phrase).split()
    if not phrase_tokens:
        return False, ""
    words = re.findall(r"\S+", transcript or "")
    normalized = [_normalize_text(word) for word in words]
    count = len(phrase_tokens)
    for start in range(len(normalized) - count + 1):
        if normalized[start:start + count] == phrase_tokens:
            remainder = " ".join(words[:start] + words[start + count:]).strip()
            return True, remainder
    return False, ""


def resolve_model(cfg: dict, phrase: str) -> str | None:
    """Return the model id/path configured for *phrase*, else a pretrained id."""
    settings = get_settings(cfg)
    if phrase in settings.models:
        return settings.models[phrase]
    return PRETRAINED_MODELS.get(phrase.strip().lower())


def capability(cfg: dict) -> dict:
    """Classify support for the configured phrase (no side effects).

    ``status`` is one of: ``invalid``, ``whisper``, ``pretrained``, ``configured``,
    ``model_missing``, ``requires_custom``, ``engine_missing``.
    """
    settings = get_settings(cfg)
    _, phrase_error = validate_phrase(settings.phrase)
    if phrase_error:
        return {"status": "invalid", "phrase": settings.phrase, "model": None, "message": phrase_error}

    engine = select_engine(cfg)
    if engine == "whisper":
        model = cfg.get("whisper_model") or config.DEFAULTS["whisper_model"]
        return {"status": "whisper", "phrase": settings.phrase, "model": model,
                "message": (f"'{settings.phrase}' is detected locally by transcribing short audio "
                            "with whisper (any language whisper supports; accuracy varies)")}
    if engine == "openwakeword":
        model = resolve_model(cfg, settings.phrase)
        if model and _model_ref_exists(model):
            status = "pretrained" if model in set(PRETRAINED_MODELS.values()) else "configured"
            return {"status": status, "phrase": settings.phrase, "model": model,
                    "message": f"model '{model}' is available for '{settings.phrase}'"}
        if model:
            return {"status": "model_missing", "phrase": settings.phrase, "model": model,
                    "message": f"model '{model}' for '{settings.phrase}' was not found"}
        return {"status": "requires_custom", "phrase": settings.phrase, "model": None,
                "message": (f"no openWakeWord model for '{settings.phrase}'; train one or set "
                            "wake_word_engine to 'whisper'")}
    return {"status": "engine_missing", "phrase": settings.phrase, "model": None,
            "message": ("no wake-word engine is available: build whisper.cpp "
                        "(scripts/setup-whisper.sh) or install openWakeWord")}


# ---------------------------------------------------------------------------
# detector interface
# ---------------------------------------------------------------------------


class WakeWordDetector:
    """Interface: consume fixed-size 16 kHz frames, return a confidence 0..1."""

    frame_samples = 1280  # 80 ms at 16 kHz

    def detect(self, frame) -> float:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        pass


class OpenWakeWordDetector(WakeWordDetector):
    """openWakeWord-backed detector. Imports the engine lazily."""

    frame_samples = 1280

    def __init__(self, model_refs: list[str], threshold: float = 0.5):
        try:
            from openwakeword.model import Model  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise WakeWordError(f"openWakeWord is not installed; {INSTALL_HINT}") from exc
        self._threshold = threshold
        self._model = Model(wakeword_models=list(model_refs), inference_framework="onnx")

    def detect(self, frame) -> float:
        import numpy as np  # provided by openWakeWord's dependencies

        audio_frame = np.asarray(frame, dtype=np.int16)
        scores = self._model.predict(audio_frame)
        return float(max(scores.values())) if scores else 0.0

    def close(self) -> None:
        self._model = None


class WhisperWakeWordDetector(WakeWordDetector):
    """Wake-word detector that reuses the local whisper.cpp pipeline.

    It keeps a rolling window of the most recent audio and, once speech is
    present and a short hop has elapsed, transcribes the window and matches the
    configured phrase. This needs no per-phrase training and works for the exact
    default Ukrainian phrase ``дідько`` (and any phrase in a language whisper
    supports). It is
    heavier than openWakeWord and only transcribes when there is speech energy.
    """

    frame_samples = 1280  # 80 ms at 16 kHz

    def __init__(self, cfg, phrase, *, window_seconds=2.5, sample_rate=16000,
                 silence_threshold_db=-50, hop_seconds=0.6):
        self._cfg = cfg
        self._phrase = phrase
        self._rate = sample_rate
        self._window_samples = max(int(window_seconds * sample_rate), sample_rate)
        self._hop_samples = max(int(hop_seconds * sample_rate), 1)
        self._silence_db = silence_threshold_db
        self._buffer = array.array("h")
        self._since = 0
        self.last_command = ""
        self.last_transcript = ""

    def detect(self, frame) -> float:
        if len(frame):
            self._buffer.extend(frame)
        if len(self._buffer) > self._window_samples:
            del self._buffer[: len(self._buffer) - self._window_samples]
        self._since += len(frame)
        if self._since < self._hop_samples:
            return 0.0
        self._since = 0
        peak = max((abs(sample) for sample in self._buffer), default=0)
        if peak <= 0 or 20 * math.log10(peak / 32768.0) < self._silence_db:
            return 0.0  # only spend transcription CPU when there is speech
        window = config.RUNTIME_DIR / "wake-window.wav"
        text, error = "", None
        try:
            audio.write_wav(window, [self._buffer], self._rate)
            try:
                text, error = speech.transcribe(self._cfg, window)
            except Exception as exc:  # noqa: BLE001 - transcription must not crash the loop
                text, error = "", str(exc)
        finally:
            window.unlink(missing_ok=True)
        if error or not text:
            return 0.0
        self.last_transcript = text
        matched, remainder = match_phrase(self._phrase, text)
        if matched:
            self.last_command = remainder
            self._buffer = array.array("h")
            self._since = 0
            return 1.0
        return 0.0

    def close(self) -> None:
        self._buffer = array.array("h")


def build_detector(cfg: dict) -> WakeWordDetector:
    """Create a detector for the configured phrase, or raise WakeWordError."""
    settings = get_settings(cfg)
    _, phrase_error = validate_phrase(settings.phrase)
    if phrase_error:
        raise WakeWordError(phrase_error)
    engine = select_engine(cfg)
    if engine == "whisper":
        return WhisperWakeWordDetector(
            cfg, settings.phrase, window_seconds=settings.window_seconds,
            sample_rate=int(cfg.get("sample_rate", 16000)),
            silence_threshold_db=float(cfg.get("silence_threshold_db", -50)),
        )
    if engine == "openwakeword":
        if not engine_available():
            raise WakeWordError(f"openWakeWord is not installed; {INSTALL_HINT}")
        model = resolve_model(cfg, settings.phrase)
        if not model:
            raise WakeWordError(capability(cfg)["message"])
        if not _model_ref_exists(model):
            raise WakeWordError(f"wake-word model '{model}' for '{settings.phrase}' was not found")
        return OpenWakeWordDetector([model], threshold=settings.threshold)
    raise WakeWordError(capability(cfg)["message"])


# ---------------------------------------------------------------------------
# activation gating and the listening loop
# ---------------------------------------------------------------------------


class TriggerGate:
    """Apply a score threshold and a cooldown to avoid repeated activations."""

    def __init__(self, threshold: float = 0.5, cooldown: float = 2.0, clock=time.monotonic):
        self._threshold = threshold
        self._cooldown = cooldown
        self._clock = clock
        self._last: float | None = None

    def check(self, score: float) -> bool:
        if score < self._threshold:
            return False
        now = self._clock()
        if self._last is not None and (now - self._last) < self._cooldown:
            return False
        self._last = now
        return True


class WakeWordListener:
    """Background listener: reads frames, calls ``on_detect`` on a trigger.

    The audio source and detector are injected, so the listener can be tested
    without a microphone or the real engine. ``start`` is idempotent (a second
    call while running is refused, so duplicate listeners cannot accumulate).
    """

    def __init__(self, detector, frame_source, on_detect, *, threshold: float = 0.5,
                 cooldown: float = 2.0, clock=time.monotonic):
        self._detector = detector
        self._source = frame_source
        self._on_detect = on_detect
        self._gate = TriggerGate(threshold, cooldown, clock)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.running:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="hyprwhispr-wakeword", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> bool:
        was_running = self.running
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        return was_running

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._source.read()
            except Exception:  # noqa: BLE001 - microphone errors must not crash
                break
            if frame is None:
                break
            try:
                score = self._detector.detect(frame)
            except Exception:  # noqa: BLE001
                break
            if self._gate.check(score):
                try:
                    self._on_detect()
                except Exception:  # noqa: BLE001 - a bad callback must not kill the loop
                    pass


class ParecFrameSource:
    """Frame source that reads raw 16-bit PCM from ``parec`` (PipeWire/PulseAudio).

    This needs no Python dependency. It uses the quiet default source unless a
    device is configured, honouring ``wake_word_device`` and then ``mic_target``.
    """

    def __init__(self, command: list[str], frame_samples: int):
        self._frame_bytes = frame_samples * 2
        self._proc = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

    def read(self):
        data = self._proc.stdout.read(self._frame_bytes)
        if not data or len(data) < self._frame_bytes:
            return None
        return array.array("h", data)

    def close(self) -> None:
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass


class SoundDeviceSource:
    """Frame source backed by the optional ``sounddevice`` package."""

    def __init__(self, stream, frame_samples: int):
        self._stream = stream
        self._frame_samples = frame_samples
        self._stream.start()

    def read(self):
        data, _overflowed = self._stream.read(self._frame_samples)
        return data[:, 0] if getattr(data, "ndim", 1) > 1 else data

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass


def default_frame_source(cfg: dict, frame_samples: int):
    """Return a microphone frame source, preferring the dependency-free parec."""
    settings = get_settings(cfg)
    rate = int(cfg.get("sample_rate", 16000))
    device = settings.device or cfg.get("mic_target")
    if shutil.which("parec"):
        command = ["parec", f"--rate={rate}", "--channels=1", "--format=s16le", "--raw"]
        if device:
            command.append(f"--device={device}")
        return ParecFrameSource(command, frame_samples)
    try:
        import sounddevice as sd  # type: ignore
    except ImportError as exc:
        raise WakeWordError(
            "no audio capture backend found: install pipewire-pulse ('parec') or the "
            "optional 'sounddevice' package"
        ) from exc
    try:
        stream = sd.InputStream(
            samplerate=rate, channels=1, dtype="int16",
            blocksize=frame_samples, device=settings.device or None,
        )
    except Exception as exc:  # noqa: BLE001 - audio backends raise many error types
        raise WakeWordError(f"could not open the microphone: {exc}") from exc
    return SoundDeviceSource(stream, frame_samples)


def capture_frames(source, seconds: float, clock=time.monotonic) -> list:
    """Read frames for a bounded number of seconds; never unbounded."""
    frames = []
    deadline = clock() + seconds
    while clock() < deadline:
        frame = source.read()
        if frame is None:
            break
        frames.append(frame)
    return frames


def run_listen(cfg: dict, command_handler, *, text_handler=None, detector_factory=build_detector,
               source_factory=default_frame_source, notify_fn=notify,
               clock=time.monotonic) -> int:
    """Foreground wake-word loop.

    Waits for the wake phrase, then captures a bounded command window and hands
    the resulting WAV to ``command_handler`` (the existing transcribe+agent
    pipeline). No audio is sent anywhere while waiting and no command reaches the
    agent unless a real detection occurred.
    """
    settings = get_settings(cfg)
    if not settings.enabled:
        raise WakeWordError(
            f"wake-word activation is off (mode is '{settings.mode}'); enable it with: "
            "hyprwhispr wake-word enable"
        )
    config.ensure_dirs()
    detector = detector_factory(cfg)
    source = source_factory(cfg, detector.frame_samples)
    gate = TriggerGate(settings.threshold, settings.cooldown, clock)
    command_wav = config.RUNTIME_DIR / "wake-command.wav"
    min_db = float(cfg.get("silence_threshold_db", -50))

    def announce() -> None:
        if settings.feedback:
            notify_fn("Wake word", f"Listening for \u201c{settings.phrase}\u201d")

    announce()
    try:
        while True:
            frame = source.read()
            if frame is None:
                break
            try:
                score = detector.detect(frame)
            except Exception as exc:  # noqa: BLE001
                log_event({"event": "wakeword_error", "error": str(exc)})
                break
            if not gate.check(score):
                continue
            log_event({"event": "wakeword_detected"})
            # One-stage: the phrase and command were spoken together (whisper engine).
            remainder = str(getattr(detector, "last_command", "") or "").strip()
            if remainder and text_handler is not None:
                if settings.feedback:
                    notify_fn("Listening", "Got it")
                try:
                    text_handler(cfg, remainder)
                except Exception:  # noqa: BLE001
                    pass
                announce()
                continue
            if settings.feedback:
                notify_fn("Listening", "Say your command")
            frames = capture_frames(source, settings.command_seconds, clock)
            if not frames:
                announce()
                continue
            audio.write_wav(command_wav, frames, int(cfg.get("sample_rate", 16000)))
            _, peak_db = audio.probe_wav(command_wav)
            if peak_db < min_db:
                notify_fn("Nothing heard", "No command was detected after the wake word.")
                command_wav.unlink(missing_ok=True)
                announce()
                continue
            command_handler(cfg, str(command_wav))
            announce()
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        detector.close()
    return 0
