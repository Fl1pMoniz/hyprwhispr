"""Command-line entry point and text rendering.

The same executable serves the compositor (``record-start`` / ``record-stop``),
interactive testing (``ask``, ``transcribe``, ``listen``) and management
(``apps``, ``games``, ``model``, ``session``, ``refresh-apps``).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import apps, audio, config, session, speech, wakeword
from .llm import loaded_models, run_pipeline, unload_model
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
  resolve <query>           show which apps/games match a query (debug)
  refresh-apps              rebuild the app and Steam indexes

Conversation:
  session                   show the current conversation context
  session clear             forget the conversation context

Activation (optional wake word; disabled by default):
  wake-word show            show the mode, wake word and capability
  wake-word set <phrase>    set the wake word (does not enable it)
  wake-word enable          enable wake word (mode: both, keeps the shortcut)
  wake-word disable         return to shortcut-only (mode: shortcut)
  wake-word mode <mode>     shortcut | wake_word | both | disabled
  wake-word check           check the engine/model for the configured phrase
  wake-word listen          run the wake-word listener in the foreground

Setup:
  list-mics                 show audio input devices
  mictest [seconds]         record and report the input level
  model                     show the model and its memory policy (alias: status)
  model status              show model, lifetime policy and loaded state
  model <small|large|name>  set the model
  model keep-alive <policy> auto | always | 0 | 10m (how long Ollama keeps it)
  model unload              release the model's memory now
  version                   print the version
"""


def show_answer(cfg: dict, transcript: str, answer: str) -> None:
    config.ensure_dirs()
    config.LAST_TRANSCRIPT.write_text(transcript or "")
    config.LAST_ANSWER.write_text(answer or "")
    if cfg.get("log_transcripts"):
        with (config.LOGS_DIR / "exchanges.log").open("a") as fh:
            fh.write(f"\n[{config.now()}]\nUSER: {transcript}\nASSISTANT: {answer}\n")
    if transcript:
        notify("You said", transcript, timeout=5000)
    notify("Assistant", answer or "(no answer)")


def _cleanup_recording(cfg: dict, wav_path: str) -> None:
    """Remove the recording unless the user asked to keep them.

    Only files inside the runtime directory are ever deleted, so passing an
    unrelated path to ``process`` can never remove user data.
    """
    if cfg.get("keep_recordings"):
        return
    target = Path(wav_path).resolve()
    try:
        target.relative_to(config.RUNTIME_DIR.resolve())
    except ValueError:
        return
    target.unlink(missing_ok=True)


def _run_turn(cfg: dict, text: str) -> str:
    state = session.load(cfg)
    answer = run_pipeline(cfg, text, state=state)
    session.save(cfg, state)
    _unload_after_turn(cfg)
    return answer


def _unload_after_turn(cfg: dict) -> None:
    """Honour an "unload after each turn" policy once the whole turn is finished.

    Best effort: skipped while a recording is in progress, and it only ever runs
    after ``run_pipeline`` (all LLM requests and tool calls) has returned. If two
    turns ran concurrently, one could release the model while another is
    mid-turn; that only costs a reload and never interrupts a request. A non-zero
    keep-alive policy avoids the situation entirely.
    """
    if not config.keep_alive_is_unload(cfg.get("keep_alive")):
        return
    if _recording_active():
        return
    ok, error = unload_model(cfg)
    log_event({"event": "model_unload_after_turn", "ok": ok, "error": error})


def _answer_text(cfg: dict, text: str) -> None:
    """Answer a text command (used for one-stage wake-word utterances)."""
    try:
        answer = _run_turn(cfg, text)
    except Exception as exc:  # noqa: BLE001
        notify("Assistant error", f"Local model call failed: {exc}", "critical")
        return
    show_answer(cfg, text, answer)
    print("Assistant:", answer)


def _transcribe_timed(cfg: dict, wav_path: str) -> tuple[str, str | None]:
    """Transcribe and log the transcription duration (no transcript content)."""
    started = time.perf_counter()
    text, error = speech.transcribe(cfg, wav_path)
    log_event({"event": "transcribe", "ms": round((time.perf_counter() - started) * 1000),
               "ok": error is None and bool(text)})
    return text, error


def handle_wav(cfg: dict, wav_path: str) -> int:
    """Transcribe a recorded wav and answer it (runs in the detached worker)."""
    pipeline_start = time.perf_counter()
    text, error = _transcribe_timed(cfg, wav_path)
    if error:
        notify("Transcription failed", error, "critical")
        log_event({"event": "transcribe_error", "error": error})
        _cleanup_recording(cfg, wav_path)
        return 1
    if not text:
        notify("Nothing recognised", "I didn't catch any speech.")
        _cleanup_recording(cfg, wav_path)
        return 0
    try:
        answer = _run_turn(cfg, text)
    except Exception as exc:  # noqa: BLE001
        notify("Assistant error", f"Local model call failed: {exc}", "critical")
        log_event({"event": "llm_error", "error": str(exc)})
        _cleanup_recording(cfg, wav_path)
        return 1
    show_answer(cfg, text, answer)
    log_event({"event": "pipeline_total", "source": "process",
               "ms": round((time.perf_counter() - pipeline_start) * 1000)})
    _cleanup_recording(cfg, wav_path)
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
    text, error = _transcribe_timed(cfg, wav)
    if error:
        print("transcription error:", error)
        return 1
    print(f"You said: {text or '(no speech recognised)'}")
    if not text:
        return 0
    try:
        answer = _run_turn(cfg, text)
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


def wake_word_command(cfg: dict, rest: list[str]) -> int:
    """Manage the optional wake-word activation (see docs/wake-word.md)."""
    sub = rest[0] if rest else "show"

    if sub == "show":
        settings = wakeword.get_settings(cfg)
        cap = wakeword.capability(cfg)
        print(f"mode: {settings.mode}")
        print(f"wake word: {settings.phrase}")
        print(f"engine: {wakeword.select_engine(cfg)} "
              f"(openWakeWord {'installed' if wakeword.engine_available() else 'not installed'})")
        print(f"capability: {cap['status']} - {cap['message']}")
        if settings.models:
            print(f"model mapping: {settings.models}")
        return 0

    if sub == "set":
        phrase = " ".join(rest[1:])
        clean, error = wakeword.validate_phrase(phrase)
        if error:
            print(f"error: {error}")
            return 2
        cfg["wake_word"] = clean
        config.save_config(cfg)
        cap = wakeword.capability(cfg)
        print(f"wake word set to \u201c{clean}\u201d (activation mode unchanged: {wakeword.get_settings(cfg).mode})")
        print(f"capability: {cap['status']} - {cap['message']}")
        return 0

    if sub in ("enable", "disable", "mode"):
        if sub == "enable":
            mode = "both"
        elif sub == "disable":
            mode = "shortcut"
        elif len(rest) >= 2:
            mode = rest[1]
        else:
            print("usage: hyprwhispr wake-word mode <shortcut|wake_word|both|disabled>")
            return 2
        _, error = wakeword.validate_mode(mode)
        if error:
            print(f"error: {error}")
            return 2
        cfg["wake_word_mode"] = mode
        config.save_config(cfg)
        print(f"wake word mode set to '{mode}'")
        if mode in ("wake_word", "both"):
            cap = wakeword.capability(cfg)
            print(f"capability: {cap['status']} - {cap['message']}")
            if cap["status"] not in ("whisper", "pretrained", "configured"):
                print("note: listening will not start until this is resolved; push-to-talk still works.")
        return 0

    if sub == "check":
        cap = wakeword.capability(cfg)
        print(f"phrase: {cap['phrase']}")
        print(f"engine: {wakeword.select_engine(cfg)} "
              f"(openWakeWord {'installed' if wakeword.engine_available() else 'not installed'})")
        print(f"status: {cap['status']}")
        print(f"message: {cap['message']}")
        return 0 if cap["status"] in ("whisper", "pretrained", "configured") else 1

    if sub == "listen":
        try:
            return wakeword.run_listen(cfg, lambda c, wav: handle_wav(c, wav), text_handler=_answer_text)
        except wakeword.WakeWordError as exc:
            print(f"error: {exc}")
            return 1

    print("usage: hyprwhispr wake-word [show|set|enable|disable|mode|check|listen]")
    return 2


def _recording_active() -> bool:
    """Best-effort check: is a push-to-talk recording in progress right now?"""
    try:
        pid = int(config.PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _same_model(name: str, model: str) -> bool:
    """Compare Ollama model names, ignoring an implicit ':latest' tag."""
    def base(text: str) -> str:
        return (text or "").split(":", 1)[0].strip().lower()

    return bool(name) and base(name) == base(model)


def _human_bytes(value: object) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def _model_status(cfg: dict) -> int:
    model = cfg["model"]
    policy = cfg.get("keep_alive", config.KEEP_ALIVE_DEFAULT)
    print(f"model: {model}")
    print(f"keep-alive policy: {config.keep_alive_policy(policy)}")
    loaded = loaded_models(cfg)
    if loaded is None:
        print("ollama: not reachable - is it running? (https://ollama.com)")
        return 1
    match = next((m for m in loaded if _same_model(m.get("name", ""), model)), None)
    if not match:
        print("loaded: no")
        if loaded:
            print("other models loaded: " + ", ".join(m["name"] for m in loaded if m.get("name")))
        return 0
    size = _human_bytes(match.get("size_vram") or match.get("size"))
    print("loaded: yes" + (f" ({size} in memory, observed - not a guarantee)" if size else ""))
    if match.get("expires_at"):
        print(f"expires: {match['expires_at']}")
    return 0


def _model_unload(cfg: dict) -> int:
    model = cfg["model"]
    if _recording_active():
        print("warning: a recording is in progress; retry after the current turn completes.")
        return 1
    ok, error = unload_model(cfg, model)
    if not ok:
        print(f"error: could not unload '{model}': {error}")
        return 1
    loaded = loaded_models(cfg)
    if loaded is None:
        print(f"requested unload of '{model}', but the Ollama API was not reachable to confirm it.")
        return 1
    if any(_same_model(m.get("name", ""), model) for m in loaded):
        print(f"'{model}' is still loaded (Ollama may need a moment, or it was just used).")
        return 1
    print(f"unloaded '{model}'.")
    print("note: actual memory reclamation depends on the Ollama version, backend and GPU driver:")
    print("      this confirms the API-level unload, not observed VRAM release.")
    return 0


def model_command(cfg: dict, rest: list[str]) -> int:
    """Show or change the model and its Ollama memory-lifetime policy."""
    sub = rest[0] if rest else None
    if sub in (None, "status"):
        return _model_status(cfg)

    if sub in ("keep-alive", "keep_alive", "keepalive", "lifetime"):
        if len(rest) < 2:
            print("usage: hyprwhispr model keep-alive <auto|always|0|10m>")
            return 2
        value, error = config.validate_keep_alive(rest[1])
        if error:
            print(f"error: {error}")
            return 2
        cfg["keep_alive"] = value
        config.save_config(cfg)
        print(f"keep-alive set to {value!r} ({config.keep_alive_policy(value)})")
        if value == "-1":
            print("note: the model now stays loaded while idle and keeps using memory until "
                  "you unload it or change this policy.")
        return 0

    if sub == "unload":
        return _model_unload(cfg)

    # Any other first argument is a model alias or name (existing behaviour).
    aliases = cfg.get("model_aliases", {"small": "qwen3:4b", "large": "qwen3:8b"})
    chosen = aliases.get(sub, sub)
    cfg["model"] = chosen
    config.save_config(cfg)
    print(f"model set to {chosen}")
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
            answer = _run_turn(cfg, text)
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
    if command == "resolve" and rest:
        print(apps.tool_resolve(cfg, " ".join(rest)))
        return 0
    if command == "refresh-apps":
        index = apps.build_app_index(cfg)
        games = apps.build_steam_games(cfg)
        print(f"indexed {len(index['apps'])} apps and {len(games['games'])} Steam games")
        return 0

    if command == "session":
        if rest and rest[0] == "clear":
            session.clear(cfg)
            print("conversation context cleared")
        else:
            print(json.dumps(session.load(cfg), indent=2, ensure_ascii=False))
        return 0

    if command == "wake-word":
        return wake_word_command(cfg, rest)

    if command == "model":
        return model_command(cfg, rest)
    if command in ("version", "-v", "--version"):
        print(f"hyprwhispr {config.VERSION}")
        return 0

    print(USAGE)
    return 2
