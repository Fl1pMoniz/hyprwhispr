"""Tests for the optional wake-word feature (no microphone, engine or network).

The real openWakeWord engine is optional and not installed in ordinary test
environments, so the detector and audio source are mocked. These tests verify
configuration, Unicode handling, activation modes, capability reporting,
gating/cooldown logic, listener lifecycle and the activation workflow — they do
NOT establish acoustic recognition quality.
"""

import pathlib
import sys
import time

import pytest

from hyprwhispr import cli, config, wakeword

CYRILLIC = "сука"
PHRASES = [CYRILLIC, "Olá assistente", "Привет помощник", "你好助手", "こんにちはアシスタント"]


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeSource:
    def __init__(self, frames):
        self._frames = list(frames)
        self.closed = False

    def read(self):
        return self._frames.pop(0) if self._frames else None

    def close(self):
        self.closed = True


class InfiniteSource:
    def read(self):
        return [0]

    def close(self):
        pass


class ErrorSource:
    def read(self):
        raise RuntimeError("microphone unplugged")

    def close(self):
        pass


class FakeDetector:
    frame_samples = 4

    def __init__(self, score):
        self._score = score
        self.calls = 0
        self.closed = False

    def detect(self, frame):
        self.calls += 1
        return self._score

    def close(self):
        self.closed = True


class ErrorDetector:
    frame_samples = 4

    def detect(self, frame):
        raise RuntimeError("inference failure")

    def close(self):
        pass


class FakeClock:
    def __init__(self, step=0.1):
        self._t = 0.0
        self._step = step

    def __call__(self):
        value = self._t
        self._t += self._step
        return value


# ---------------------------------------------------------------------------
# configuration and Unicode
# ---------------------------------------------------------------------------


def test_default_phrase_is_exact_ukrainian():
    # Distinguish the (Ukrainian) default from the generic Cyrillic sample used below.
    assert config.DEFAULTS["wake_word"] == "\u0434\u0456\u0434\u044c\u043a\u043e"  # д і д ь к о
    assert config.DEFAULTS["wake_word"] == wakeword.DEFAULT_WAKE_WORD == "дідько"


def test_wake_word_disabled_by_default():
    assert config.DEFAULTS["wake_word_mode"] == "shortcut"
    assert wakeword.get_settings(config.DEFAULTS).enabled is False


def test_old_config_without_wake_fields_is_compatible(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"model": "qwen3:4b"}')
    cfg = config.load_config(path)
    assert cfg["wake_word"] == wakeword.DEFAULT_WAKE_WORD
    assert cfg["wake_word_mode"] == "shortcut"


@pytest.mark.parametrize("phrase", PHRASES)
def test_unicode_phrases_roundtrip(tmp_path, phrase):
    path = tmp_path / "config.json"
    cfg = config.load_config(path)
    cfg["wake_word"] = phrase
    config.save_config(cfg, path)
    assert config.load_config(path)["wake_word"] == phrase


def test_changing_phrase_preserves_unrelated_settings(tmp_path):
    path = tmp_path / "config.json"
    cfg = config.load_config(path)
    cfg["model"] = "custom:7b"
    cfg["wake_word"] = CYRILLIC
    config.save_config(cfg, path)
    cfg = config.load_config(path)
    cfg["wake_word"] = "您好助手"
    config.save_config(cfg, path)
    reloaded = config.load_config(path)
    assert reloaded["model"] == "custom:7b"
    assert reloaded["wake_word"] == "您好助手"


def test_validate_phrase_accepts_and_trims():
    assert wakeword.validate_phrase("  сука  ") == (CYRILLIC, None)
    assert wakeword.validate_phrase("你好助手") == ("你好助手", None)
    assert wakeword.validate_phrase("hey jarvis") == ("hey jarvis", None)


@pytest.mark.parametrize("bad", ["", "   ", "x" * 65, "bad\nword", "tab\there", 3, None])
def test_validate_phrase_rejects_bad_values(bad):
    clean, error = wakeword.validate_phrase(bad)
    assert clean is None and error


def test_validate_mode():
    for mode in ("shortcut", "wake_word", "both", "disabled"):
        assert wakeword.validate_mode(mode) == (mode, None)
    for bad in ("", "Shortcut", "listening", None):
        assert wakeword.validate_mode(bad)[1]


def test_settings_error_reports_invalid_mode_and_phrase():
    assert wakeword.settings_error({"wake_word_mode": "nope"}) is not None
    assert wakeword.settings_error({"wake_word": "   "}) is not None
    assert wakeword.settings_error({}) is None


# ---------------------------------------------------------------------------
# capability classification
# ---------------------------------------------------------------------------


def _fake_engine(monkeypatch, available=True):
    monkeypatch.setattr(wakeword, "engine_available", lambda: available)


def test_capability_engine_missing(monkeypatch):
    _fake_engine(monkeypatch, False)
    cap = wakeword.capability({"wake_word": CYRILLIC})
    assert cap["status"] == "engine_missing"
    assert "openWakeWord" in cap["message"]


def test_capability_default_phrase_requires_custom_model(monkeypatch):
    _fake_engine(monkeypatch, True)
    cap = wakeword.capability({"wake_word": CYRILLIC})
    assert cap["status"] == "requires_custom"
    assert cap["model"] is None


def test_capability_english_pretrained(monkeypatch):
    _fake_engine(monkeypatch, True)
    cap = wakeword.capability({"wake_word": "hey jarvis"})
    assert cap["status"] == "pretrained"
    assert cap["model"] == "hey_jarvis"


def test_capability_configured_custom_model(monkeypatch, tmp_path):
    _fake_engine(monkeypatch, True)
    model = tmp_path / "suka.onnx"
    model.write_bytes(b"x")
    cap = wakeword.capability({"wake_word": CYRILLIC, "wake_word_models": {CYRILLIC: str(model)}})
    assert cap["status"] == "configured"


def test_capability_model_missing(monkeypatch):
    _fake_engine(monkeypatch, True)
    cap = wakeword.capability({"wake_word": CYRILLIC, "wake_word_models": {CYRILLIC: "/no/such.onnx"}})
    assert cap["status"] == "model_missing"


def test_capability_invalid_phrase(monkeypatch):
    _fake_engine(monkeypatch, True)
    cap = wakeword.capability({"wake_word": "   "})
    assert cap["status"] == "invalid"


def test_build_detector_reports_missing_engine(monkeypatch):
    _fake_engine(monkeypatch, False)
    with pytest.raises(wakeword.WakeWordError) as excinfo:
        wakeword.build_detector({"wake_word": CYRILLIC})
    assert "openWakeWord" in str(excinfo.value)


def test_build_detector_reports_missing_model(monkeypatch):
    _fake_engine(monkeypatch, True)
    with pytest.raises(wakeword.WakeWordError):
        wakeword.build_detector({"wake_word": CYRILLIC})  # no model mapped


# ---------------------------------------------------------------------------
# gating / cooldown
# ---------------------------------------------------------------------------


def test_trigger_gate_threshold():
    gate = wakeword.TriggerGate(threshold=0.5, cooldown=0, clock=FakeClock())
    assert gate.check(0.4) is False
    assert gate.check(0.9) is True


def test_trigger_gate_cooldown_suppresses_repeats():
    gate = wakeword.TriggerGate(threshold=0.5, cooldown=10.0, clock=FakeClock(step=0.1))
    assert gate.check(0.9) is True   # first trigger
    assert gate.check(0.9) is False  # within cooldown
    assert gate.check(0.9) is False


def test_trigger_gate_allows_after_cooldown():
    gate = wakeword.TriggerGate(threshold=0.5, cooldown=0.25, clock=FakeClock(step=0.1))
    assert gate.check(0.9) is True    # t=0.0
    assert gate.check(0.9) is False   # t=0.1 (within cooldown)
    assert gate.check(0.9) is False   # t=0.2 (within cooldown)
    assert gate.check(0.9) is True    # t=0.3 (cooldown elapsed)


# ---------------------------------------------------------------------------
# listener lifecycle
# ---------------------------------------------------------------------------


def test_listener_invokes_callback_respecting_cooldown():
    calls = []
    listener = wakeword.WakeWordListener(
        FakeDetector(0.9), FakeSource([[1], [1], [1]]), lambda: calls.append(1),
        threshold=0.5, cooldown=10.0, clock=FakeClock(step=0.1),
    )
    listener._run()  # synchronous, deterministic
    assert calls == [1]


def test_listener_ignores_low_scores():
    calls = []
    listener = wakeword.WakeWordListener(
        FakeDetector(0.1), FakeSource([[1], [1], [1]]), lambda: calls.append(1),
        threshold=0.5, cooldown=0.0, clock=FakeClock(),
    )
    listener._run()
    assert calls == []


def test_listener_handles_source_error_gracefully():
    listener = wakeword.WakeWordListener(
        FakeDetector(0.9), ErrorSource(), lambda: None, clock=FakeClock(),
    )
    listener._run()  # must not raise


def test_listener_stops_on_none_frame():
    listener = wakeword.WakeWordListener(
        FakeDetector(0.9), FakeSource([None]), lambda: None, clock=FakeClock(),
    )
    listener._run()


def test_listener_start_stop_and_duplicate_prevention():
    listener = wakeword.WakeWordListener(
        FakeDetector(0.0), InfiniteSource(), lambda: None, threshold=0.5, cooldown=1.0,
    )
    try:
        assert listener.start() is True
        assert listener.running is True
        assert listener.start() is False  # duplicate refused
        assert listener.stop() is True
        assert listener.running is False
    finally:
        listener.stop()


# ---------------------------------------------------------------------------
# activation workflow
# ---------------------------------------------------------------------------


def _enabled_cfg(**overrides):
    cfg = {
        "wake_word_mode": "wake_word",
        "wake_word": CYRILLIC,
        "sample_rate": 16000,
        "wake_word_feedback": False,
        "wake_word_threshold": 0.5,
        "wake_word_cooldown_seconds": 0.0,
        "wake_word_command_seconds": 5,
        "silence_threshold_db": -50,
    }
    cfg.update(overrides)
    return cfg


def test_run_listen_requires_enabled_mode():
    with pytest.raises(wakeword.WakeWordError):
        wakeword.run_listen({"wake_word_mode": "shortcut"}, lambda c, w: None)


def test_run_listen_triggers_command_on_detection():
    handled = []
    detector = FakeDetector(0.9)
    source = FakeSource([[3000, -3000]] * 30 + [None])
    rc = wakeword.run_listen(
        _enabled_cfg(), lambda c, wav: handled.append(pathlib.Path(wav)),
        detector_factory=lambda c: detector, source_factory=lambda c, n: source,
        notify_fn=lambda *a, **k: None,
    )
    assert rc == 0
    assert len(handled) == 1 and handled[0].exists()
    assert detector.closed and source.closed


def test_run_listen_never_calls_command_without_detection():
    handled = []
    detector = FakeDetector(0.1)  # below threshold
    source = FakeSource([[3000, -3000]] * 10 + [None])
    wakeword.run_listen(
        _enabled_cfg(), lambda c, wav: handled.append(wav),
        detector_factory=lambda c: detector, source_factory=lambda c, n: source,
        notify_fn=lambda *a, **k: None,
    )
    assert handled == []


def test_run_listen_ignores_silent_command():
    handled = []
    messages = []
    detector = FakeDetector(0.9)
    source = FakeSource([[0, 0]] * 30 + [None])
    wakeword.run_listen(
        _enabled_cfg(), lambda c, wav: handled.append(wav),
        detector_factory=lambda c: detector, source_factory=lambda c, n: source,
        notify_fn=lambda title, body=None, **k: messages.append(title),
    )
    assert handled == []
    assert any("Nothing" in m for m in messages)


def test_run_listen_handles_detector_error():
    source = FakeSource([[1], [1], [1], [None]])
    rc = wakeword.run_listen(
        _enabled_cfg(), lambda c, wav: None,
        detector_factory=lambda c: ErrorDetector(), source_factory=lambda c, n: source,
        notify_fn=lambda *a, **k: None,
    )
    assert rc == 0


def test_run_listen_feedback_notifies():
    messages = []
    source = FakeSource([[0, 0]] * 5 + [None])  # low energy -> silent command path
    wakeword.run_listen(
        _enabled_cfg(wake_word_feedback=True), lambda c, wav: None,
        detector_factory=lambda c: FakeDetector(0.9), source_factory=lambda c, n: source,
        notify_fn=lambda title, body=None, **k: messages.append(title),
    )
    assert "Wake word" in messages


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _use_tmp_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")


def test_cli_show_defaults(monkeypatch, capsys, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    assert cli.main(["wake-word", "show"]) == 0
    out = capsys.readouterr().out
    assert wakeword.DEFAULT_WAKE_WORD in out and "shortcut" in out


def test_cli_set_does_not_enable(monkeypatch, capsys, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    assert cli.main(["wake-word", "set", "Olá assistente"]) == 0
    cfg = config.load_config(tmp_path / "config.json")
    assert cfg["wake_word"] == "Olá assistente"
    assert cfg["wake_word_mode"] == "shortcut"  # unchanged


def test_cli_set_rejects_empty(monkeypatch, capsys, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    assert cli.main(["wake-word", "set", ""]) == 2
    assert "error" in capsys.readouterr().out.lower()


def test_cli_enable_and_disable(monkeypatch, capsys, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    assert cli.main(["wake-word", "enable"]) == 0
    assert config.load_config(tmp_path / "config.json")["wake_word_mode"] == "both"
    assert cli.main(["wake-word", "disable"]) == 0
    assert config.load_config(tmp_path / "config.json")["wake_word_mode"] == "shortcut"


def test_cli_invalid_mode(monkeypatch, capsys, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    assert cli.main(["wake-word", "mode", "listening"]) == 2
    assert "error" in capsys.readouterr().out.lower()


def test_cli_check_reports_engine_state(monkeypatch, capsys, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    rc = cli.main(["wake-word", "check"])
    out = capsys.readouterr().out
    assert wakeword.DEFAULT_WAKE_WORD in out
    # the engine is not installed in the test environment -> not ready
    assert rc == 1
    assert "engine" in out.lower()


# ---------------------------------------------------------------------------
# whisper engine (the default; works for any phrase, e.g. сука)
# ---------------------------------------------------------------------------


class RemainderDetector:
    frame_samples = 4

    def __init__(self, score, remainder=""):
        self._score = score
        self.last_command = remainder
        self.closed = False

    def detect(self, frame):
        return self._score

    def close(self):
        self.closed = True


def _whisper_cfg(tmp_path, **overrides):
    binary = tmp_path / "whisper-cli"
    binary.write_text("")
    model = tmp_path / "ggml-small.bin"
    model.write_bytes(b"x")
    cfg = {
        "wake_word_mode": "wake_word",
        "wake_word": CYRILLIC,
        "whisper_bin": str(binary),
        "whisper_model": str(model),
        "sample_rate": 16000,
        "wake_word_feedback": False,
        "wake_word_command_seconds": 5,
        "silence_threshold_db": -50,
    }
    cfg.update(overrides)
    return cfg


def test_match_phrase_extracts_command():
    assert wakeword.match_phrase(CYRILLIC, "сука открой firefox") == (True, "открой firefox")
    assert wakeword.match_phrase("Сука!", "Сука, открой Firefox.") == (True, "открой Firefox.")
    assert wakeword.match_phrase(CYRILLIC, "привет как дела") == (False, "")
    assert wakeword.match_phrase(CYRILLIC, "") == (False, "")


def test_select_engine_prefers_openwakeword_model(monkeypatch, tmp_path):
    monkeypatch.setattr(wakeword, "engine_available", lambda: True)
    monkeypatch.setattr(wakeword, "_whisper_available", lambda cfg: True)
    model = tmp_path / "m.onnx"
    model.write_bytes(b"x")
    assert wakeword.select_engine({"wake_word": CYRILLIC, "wake_word_models": {CYRILLIC: str(model)}}) == "openwakeword"


def test_select_engine_falls_back_to_whisper(monkeypatch):
    monkeypatch.setattr(wakeword, "engine_available", lambda: False)
    monkeypatch.setattr(wakeword, "_whisper_available", lambda cfg: True)
    assert wakeword.select_engine({"wake_word": CYRILLIC}) == "whisper"


def test_select_engine_none_when_nothing_available(monkeypatch):
    monkeypatch.setattr(wakeword, "engine_available", lambda: False)
    monkeypatch.setattr(wakeword, "_whisper_available", lambda cfg: False)
    assert wakeword.select_engine({"wake_word": CYRILLIC}) == "none"


def test_capability_whisper(monkeypatch):
    monkeypatch.setattr(wakeword, "engine_available", lambda: False)
    monkeypatch.setattr(wakeword, "_whisper_available", lambda cfg: True)
    cap = wakeword.capability({"wake_word": CYRILLIC})
    assert cap["status"] == "whisper"


def test_build_detector_whisper(monkeypatch, tmp_path):
    cfg = _whisper_cfg(tmp_path, wake_word_engine="whisper")
    detector = wakeword.build_detector(cfg)
    assert isinstance(detector, wakeword.WhisperWakeWordDetector)


def test_whisper_detector_triggers_and_extracts_command(monkeypatch, tmp_path):
    cfg = _whisper_cfg(tmp_path)
    monkeypatch.setattr(wakeword.speech, "transcribe", lambda c, w: ("сука открой firefox", None))
    detector = wakeword.WhisperWakeWordDetector(cfg, CYRILLIC, window_seconds=1.0,
                                                hop_seconds=0.2, sample_rate=16000)
    score = 0.0
    for _ in range(5):  # enough frames to pass the hop
        score = detector.detect([3000] * 1280)
        if score:
            break
    assert score == 1.0
    assert detector.last_command == "открой firefox"


def test_whisper_detector_ignores_non_match(monkeypatch, tmp_path):
    cfg = _whisper_cfg(tmp_path)
    monkeypatch.setattr(wakeword.speech, "transcribe", lambda c, w: ("как дела", None))
    detector = wakeword.WhisperWakeWordDetector(cfg, CYRILLIC, hop_seconds=0.1)
    for _ in range(5):
        assert detector.detect([3000] * 1280) == 0.0
    assert detector.last_command == ""


def test_whisper_detector_skips_silence(monkeypatch, tmp_path):
    cfg = _whisper_cfg(tmp_path)
    called = []
    monkeypatch.setattr(wakeword.speech, "transcribe", lambda c, w: called.append(1) or ("сука", None))
    detector = wakeword.WhisperWakeWordDetector(cfg, CYRILLIC, hop_seconds=0.05)
    for _ in range(5):
        assert detector.detect([0] * 1280) == 0.0
    assert called == []  # no transcription for silence


def test_run_listen_one_stage_uses_text_handler():
    text_calls, wav_calls = [], []
    detector = RemainderDetector(0.9, remainder="открой firefox")
    source = FakeSource([[3000, -3000]] * 5 + [None])
    wakeword.run_listen(
        _enabled_cfg(wake_word_cooldown_seconds=999.0), lambda c, wav: wav_calls.append(wav),
        text_handler=lambda c, t: text_calls.append(t),
        detector_factory=lambda c: detector, source_factory=lambda c, n: source,
        notify_fn=lambda *a, **k: None,
    )
    assert text_calls == ["открой firefox"]
    assert wav_calls == []  # one-stage: no separate command recording


# ---------------------------------------------------------------------------
# audio frame source (dependency-free parec backend)
# ---------------------------------------------------------------------------


class _FakeStdout:
    def __init__(self, chunk):
        self._chunk = chunk

    def read(self, n):
        return self._chunk[:n]


class _FakeProc:
    def __init__(self, chunk):
        self.stdout = _FakeStdout(chunk)
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_default_frame_source_prefers_parec(monkeypatch):
    proc = _FakeProc(b"\x00\x01" * 1280)
    monkeypatch.setattr(wakeword.shutil, "which", lambda name: "/usr/bin/parec" if name == "parec" else None)
    monkeypatch.setattr(wakeword.subprocess, "Popen", lambda *a, **k: proc)
    source = wakeword.default_frame_source({"sample_rate": 16000}, 1280)
    assert isinstance(source, wakeword.ParecFrameSource)
    frame = source.read()
    assert len(frame) == 1280
    source.close()
    assert proc.terminated


def test_default_frame_source_reports_no_backend(monkeypatch):
    monkeypatch.setattr(wakeword.shutil, "which", lambda name: None)
    monkeypatch.setitem(sys.modules, "sounddevice", None)  # make the import fail
    with pytest.raises(wakeword.WakeWordError):
        wakeword.default_frame_source({"sample_rate": 16000}, 1280)
