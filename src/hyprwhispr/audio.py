"""Microphone capture using PipeWire's ``pw-record`` (PulseAudio's ``parecord``
also works by changing the ``recorder`` setting).

The push-to-talk flow is two short-lived commands driven by the compositor:

* ``record-start``  spawns the recorder in the background and remembers its pid
* ``record-stop``   stops the recorder and hands the file to a worker process

Nothing listens to the microphone except between those two calls.
"""

from __future__ import annotations

import array
import math
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
import wave

from . import config
from .notify import log_event, notify


def probe_wav(path: pathlib.Path) -> tuple[int, float]:
    """Return ``(duration_ms, peak_dbfs)`` for a 16-bit PCM WAV file.

    Returns ``(0, -inf)`` when the file cannot be read. This is used to reject
    accidental taps and silent recordings before spending time on whisper.
    """
    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            width = wav.getsampwidth()
            raw = wav.readframes(frames)
    except (wave.Error, OSError):
        return 0, float("-inf")
    if rate <= 0:
        return 0, float("-inf")
    duration_ms = int(1000 * frames / rate)
    if width != 2:
        return duration_ms, float("-inf")
    try:
        samples = array.array("h")
        samples.frombytes(raw)
    except ValueError:
        return duration_ms, float("-inf")
    peak = max((abs(sample) for sample in samples), default=0)
    if peak <= 0:
        return duration_ms, float("-inf")
    return duration_ms, 20 * math.log10(peak / 32768.0)


def write_wav(path: pathlib.Path, frames, rate: int = 16000, channels: int = 1,
              width: int = 2) -> pathlib.Path:
    """Write 16-bit PCM frames to a WAV file.

    ``frames`` is an iterable of per-frame sample sequences (plain lists, the
    stdlib ``array`` type, or numpy int16 arrays). Kept dependency-free.
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        for frame in frames:
            if hasattr(frame, "tobytes"):  # numpy array
                if str(getattr(frame, "dtype", "int16")) != "int16":
                    frame = frame.astype("int16")
                wav.writeframes(frame.tobytes())
            else:
                wav.writeframes(array.array("h", frame).tobytes())
    return path


def _recorder_command(cfg: dict, output: pathlib.Path) -> list[str]:
    recorder = shutil.which(cfg["recorder"]) or cfg["recorder"]
    cmd = [recorder, "--rate", str(cfg["sample_rate"]), "--channels", "1", "--format", "s16"]
    if cfg.get("mic_target"):
        cmd += ["--target", str(cfg["mic_target"])]
    cmd += [str(output)]
    return cmd


def _open_recorder_log():
    return (config.LOGS_DIR / "recorder.log").open("a")


def record_start(cfg: dict) -> int:
    """Begin capturing audio (invoked on hotkey press)."""
    config.ensure_dirs()
    if not config.is_enabled(cfg):
        notify("hyprwhispr is off", "Enable it with: hyprwhispr power on")
        return 1
    if config.PIDFILE.exists():
        try:
            old_pid = int(config.PIDFILE.read_text().strip())
            os.kill(old_pid, 0)
            notify("Already listening", "Voice capture is already running.")
            return 0
        except (ValueError, ProcessLookupError, PermissionError):
            config.PIDFILE.unlink(missing_ok=True)

    proc = subprocess.Popen(
        _recorder_command(cfg, config.WAVFILE),
        stdout=subprocess.DEVNULL, stderr=_open_recorder_log(), start_new_session=True,
    )
    config.PIDFILE.write_text(str(proc.pid))
    log_event({"event": "record_start", "pid": proc.pid})
    notify("Listening...", "Hold the key, speak in any language, then release.", timeout=4000)
    return 0


def record_stop(cfg: dict) -> int:
    """Stop capturing and process the clip in a detached worker (invoked on release)."""
    config.ensure_dirs()
    if not config.PIDFILE.exists():
        return 0
    try:
        pid = int(config.PIDFILE.read_text().strip())
    except ValueError:
        config.PIDFILE.unlink(missing_ok=True)
        return 0

    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        pass
    for _ in range(20):
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            break
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    held_ms = None
    try:  # approximate how long the key was held, from the pidfile's mtime
        held_ms = round((time.time() - config.PIDFILE.stat().st_mtime) * 1000)
    except OSError:
        pass
    config.PIDFILE.unlink(missing_ok=True)
    log_event({"event": "record_stop", "pid": pid, "held_ms": held_ms})

    if not config.is_enabled(cfg):
        notify("hyprwhispr is off", "The recording was discarded.")
        return 0

    if not config.WAVFILE.exists() or config.WAVFILE.stat().st_size < 2000:
        notify("Nothing recorded", "The clip was too short - hold the key while you speak.")
        return 0

    duration_ms, peak_db = probe_wav(config.WAVFILE)
    min_ms = int(cfg.get("min_record_ms", 300))
    if duration_ms and duration_ms < min_ms:
        log_event({"event": "record_rejected", "reason": "too_short", "ms": duration_ms})
        notify("Too short", f"Hold the key a little longer than {min_ms} ms.")
        return 0
    if peak_db < float(cfg.get("silence_threshold_db", -50)):
        log_event({"event": "record_rejected", "reason": "silence", "peak_db": round(peak_db, 1)})
        notify("No speech detected", "I only heard silence - check your microphone.")
        return 0

    subprocess.Popen(
        [sys.executable, "-m", "hyprwhispr", "process", str(config.WAVFILE)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return 0


def record_seconds(cfg: dict, seconds: int, output: pathlib.Path) -> bool:
    """Record for a fixed number of seconds. Returns True if audio was captured."""
    output.unlink(missing_ok=True)
    proc = subprocess.Popen(
        _recorder_command(cfg, output),
        stdout=subprocess.DEVNULL, stderr=_open_recorder_log(),
    )
    time.sleep(seconds)
    if proc.poll() is not None:
        return False
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    return output.exists() and output.stat().st_size > 2000


def list_mics() -> int:
    """Print the PipeWire audio sources and how to reference one."""
    try:
        out = subprocess.run(["wpctl", "status"], capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        print("wpctl not found (install pipewire-utils)")
        return 1
    printing = False
    for line in out.splitlines():
        if "Sources:" in line:
            printing = True
        elif "Filters:" in line:
            printing = False
        if printing:
            print(line)
    print("\nTo use a specific device, run:  wpctl inspect <id> | grep node.name")
    print("and put that node.name in the \"mic_target\" setting.")
    return 0


def mictest(cfg: dict, seconds: int = 4) -> int:
    """Record from the configured mic and report the captured level."""
    config.ensure_dirs()
    wav = config.RUNTIME_DIR / "mictest.wav"
    notify("Mic test", f"Speak now for {seconds} seconds into your mic...", timeout=seconds * 1000)
    if not record_seconds(cfg, seconds, wav):
        print("recorder exited early; check the target device name")
        return 1
    print(f"device: {cfg.get('mic_target') or 'system default'}")
    print(f"captured: {wav} ({wav.stat().st_size} bytes, {seconds}s)")
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(wav), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        print("ffmpeg not found; install ffmpeg for level analysis")
        return 0
    for line in result.stderr.splitlines():
        if "mean_volume" in line or "max_volume" in line:
            print("  " + line.strip())
    verdict = "OK - your mic is being captured" if "max_volume" in result.stderr else "could not analyse"
    print(verdict)
    notify("Mic test", verdict, timeout=5000)
    return 0
