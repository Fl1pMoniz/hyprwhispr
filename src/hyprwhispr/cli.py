"""Command-line entry point and text rendering.

The same executable serves the compositor (``record-start`` / ``record-stop``),
interactive testing (``ask``, ``transcribe``, ``listen``) and management
(``apps``, ``games``, ``model``, ``refresh-apps``).
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys

from . import apps, audio, config, speech
from .llm import run_pipeline
from .notify import log_event, notify

USAGE = """\
hyprwhispr - local push-to-talk desktop assistant

Usage: hyprwhispr <command> [args]

Push-to-talk (bound in your compositor):
  record-start              begin capturing the microphone
  record-stop               stop capturing and answer

Ask / test from a terminal:
  ask <text...>             run the model + tools on typed text
  listen [seconds]          record, transcribe and answer (default 6s)
  transcribe <file.wav>     transcribe a wav file only
  process <file.wav>        transcribe a wav and answer (used by record-stop)
  read                      show the last exchange in a terminal

Applications and games:
  apps [filter]             list installed desktop apps
  games [filter]            list installed Steam games
  launch <app>              open an app or game by name
  play <game>               launch a Steam game by name
  close <name>              close an app or game by name
  refresh-apps              rebuild the app and Steam indexes

Setup:
  list-mics                 show audio input devices
  mictest [seconds]         record and report the input level
  model [small|large|name]  show or set the model
  version                   print the version
"""


def show_answer(cfg: dict, transcript: str, answer: str) -> None:
    config.ensure_dirs()
    config.LAST_TRANSCRIPT.write_text(transcript or "")
    config.LAST_ANSWER.write_text(answer or "")
    with (config.LOGS_DIR / "exchanges.log").open("a") as fh:
        fh.write(f"\n[{config.now()}]\nUSER: {transcript}\nASSISTANT: {answer}\n")
    if transcript:
        notify("You said", transcript, timeout=5000)
    notify("Assistant", answer or "(no answer)")


def handle_wav(cfg: dict, wav_path: str) -> int:
    """Transcribe a recorded wav and answer it (runs in the detached worker)."""
    text, error = speech.transcribe(cfg, wav_path)
    if error:
        notify("Transcription failed", error, "critical")
        log_event({"event": "transcribe_error", "error": error})
        return 1
    if not text:
        notify("Nothing recognised", "I didn't catch any speech.")
        return 0
    try:
        answer = run_pipeline(cfg, text)
    except Exception as exc:  # noqa: BLE001
        notify("Assistant error", f"Local model call failed: {exc}", "critical")
        log_event({"event": "llm_error", "error": str(exc)})
        return 1
    show_answer(cfg, text, answer)
    return 0


def listen(cfg: dict, seconds: int = 6) -> int:
    """Terminal-friendly test: record, print the transcript and the answer."""
    config.ensure_dirs()
    wav = config.RUNTIME_DIR / "listen.wav"
    print(f"Recording {seconds}s from {cfg.get('mic_target') or 'system default'} - speak now...")
    notify("Listening", f"Speak now for {seconds} seconds", timeout=seconds * 1000)
    if not audio.record_seconds(cfg, seconds, wav):
        print("recorder failed to start - check the mic device name")
        return 1
    text, error = speech.transcribe(cfg, wav)
    if error:
        print("transcription error:", error)
        return 1
    print(f"You said: {text or '(no speech recognised)'}")
    if not text:
        return 0
    try:
        answer = run_pipeline(cfg, text)
    except Exception as exc:  # noqa: BLE001
        print("model error:", exc)
        return 1
    show_answer(cfg, text, answer)
    print("Assistant:", answer)
    return 0


def show_last() -> int:
    if not config.LAST_TRANSCRIPT.exists() and not config.LAST_ANSWER.exists():
        notify("Assistant", "No previous exchange.")
        return 0
    body = (
        "You said:\n" + config.LAST_TRANSCRIPT.read_text()
        + "\n\nAssistant:\n" + (config.LAST_ANSWER.read_text() if config.LAST_ANSWER.exists() else "")
    )
    view_file = config.RUNTIME_DIR / "last-view.txt"
    view_file.write_text(body)
    terminal = shutil.which("kitty")
    if terminal:
        subprocess.Popen(
            [terminal, "--class", "hyprwhispr-view", "-T", "hyprwhispr", "-e",
             "sh", "-c", f"cat {shlex.quote(str(view_file))}; printf '\\n\\n[Enter to close] '; read _"],
            start_new_session=True,
        )
    else:
        notify("Assistant", body[:1500])
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    config.ensure_dirs()
    cfg = config.load_config()
    if not argv:
        print(USAGE)
        return 2
    command, rest = argv[0], argv[1:]

    if command == "record-start":
        return audio.record_start(cfg)
    if command == "record-stop":
        return audio.record_stop(cfg)
    if command == "transcribe" and rest:
        text, error = speech.transcribe(cfg, rest[0])
        print(text if not error else f"ERROR: {error}")
        return 0 if not error else 1
    if command == "process" and rest:
        return handle_wav(cfg, rest[0])
    if command == "ask" and rest:
        text = " ".join(rest)
        try:
            answer = run_pipeline(cfg, text)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}")
            return 1
        show_answer(cfg, text, answer)
        print(answer)
        return 0
    if command == "listen":
        return listen(cfg, int(rest[0]) if rest else 6)
    if command == "read":
        return show_last()
    if command == "list-mics":
        return audio.list_mics()
    if command == "mictest":
        return audio.mictest(cfg, int(rest[0]) if rest else 4)

    if command == "apps":
        print(apps.tool_list_apps(cfg, " ".join(rest)))
        return 0
    if command == "games":
        print(apps.tool_list_steam_games(cfg, " ".join(rest)))
        return 0
    if command == "launch" and rest:
        print(apps.tool_open_app(cfg, " ".join(rest)))
        return 0
    if command == "play" and rest:
        print(apps.tool_launch_steam_game(cfg, " ".join(rest)))
        return 0
    if command == "close" and rest:
        print(apps.tool_close_app(cfg, " ".join(rest)))
        return 0
    if command == "refresh-apps":
        index = apps.build_app_index(cfg)
        games = apps.build_steam_games(cfg)
        print(f"indexed {len(index['apps'])} apps and {len(games['games'])} Steam games")
        return 0

    if command == "model":
        if rest:
            chosen = {"small": "qwen3:4b", "large": "qwen3:8b"}.get(rest[0], rest[0])
            cfg["model"] = chosen
            config.save_config(cfg)
            print(f"model set to {chosen}")
        else:
            print(f"current model: {cfg['model']}  (num_ctx={cfg['num_ctx']}, keep_alive={cfg.get('keep_alive')})")
        return 0
    if command in ("version", "-v", "--version"):
        print(f"hyprwhispr {config.VERSION}")
        return 0

    print(USAGE)
    return 2
