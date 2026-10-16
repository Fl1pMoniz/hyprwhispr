import subprocess

from hyprwhispr import speech


def _cfg(tmp_path, gpu=True):
    binary = tmp_path / "whisper-cli"
    binary.write_text("")
    model = tmp_path / "model.bin"
    model.write_text("")
    return {"whisper_bin": str(binary), "whisper_model": str(model), "whisper_gpu": gpu}


def test_clean_transcript_removes_markers_and_repeats():
    assert speech.clean_transcript("[BLANK_AUDIO]") == ""
    assert speech.clean_transcript("open the the the file") == "open the file"
    assert speech.clean_transcript("Firefox  Firefox") == "Firefox"


def test_transcribe_missing_binary():
    cfg = {"whisper_bin": "/nonexistent/whisper-cli", "whisper_model": "/nonexistent/model.bin"}
    text, error = speech.transcribe(cfg, "/tmp/none.wav")
    assert text == "" and "whisper binary not found" in error


def test_transcribe_missing_model(tmp_path):
    binary = tmp_path / "whisper-cli"
    binary.write_text("")
    cfg = {"whisper_bin": str(binary), "whisper_model": "/nonexistent/model.bin"}
    text, error = speech.transcribe(cfg, "/tmp/none.wav")
    assert "whisper model not found" in error


def _writes_transcript(out_prefix):
    out_prefix.with_suffix(".txt").write_text("hello world\n")


def test_transcribe_success(monkeypatch, tmp_path):
    calls = []

    def fake_run(cfg, wav, out_prefix, use_gpu, timeout):
        calls.append(use_gpu)
        _writes_transcript(out_prefix)
        return subprocess.CompletedProcess([], 0, b"", b"")

    monkeypatch.setattr(speech, "_run_whisper", fake_run)
    text, error = speech.transcribe(_cfg(tmp_path), "/tmp/a.wav")
    assert error is None and text == "hello world"
    assert calls == [True]


def test_transcribe_timeout(monkeypatch, tmp_path):
    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired("whisper", 1)

    monkeypatch.setattr(speech, "_run_whisper", fake_run)
    text, error = speech.transcribe(_cfg(tmp_path), "/tmp/a.wav")
    assert "timed out" in error


def test_transcribe_gpu_falls_back_to_cpu(monkeypatch, tmp_path):
    calls = []

    def fake_run(cfg, wav, out_prefix, use_gpu, timeout):
        calls.append(use_gpu)
        if use_gpu:
            raise subprocess.CalledProcessError(1, "whisper", stderr=b"CUDA error: no CUDA-capable device")
        _writes_transcript(out_prefix)
        return subprocess.CompletedProcess([], 0, b"", b"")

    monkeypatch.setattr(speech, "_run_whisper", fake_run)
    text, error = speech.transcribe(_cfg(tmp_path, gpu=True), "/tmp/a.wav")
    assert error is None and text == "hello world"
    assert calls == [True, False]  # tried GPU, then CPU


def test_transcribe_cpu_failure_returns_error(monkeypatch, tmp_path):
    def fake_run(*a, **k):
        raise subprocess.CalledProcessError(1, "whisper", stderr=b"boom")

    monkeypatch.setattr(speech, "_run_whisper", fake_run)
    text, error = speech.transcribe(_cfg(tmp_path, gpu=False), "/tmp/a.wav")
    assert text == "" and "whisper failed" in error


# --- language handling -------------------------------------------------------


def _cmd_cfg(tmp_path, model="model.bin", language=None, gpu=True):
    binary = tmp_path / "whisper-cli"
    binary.write_text("")
    model_path = tmp_path / model
    model_path.write_text("")
    return {"whisper_bin": str(binary), "whisper_model": str(model_path),
            "whisper_gpu": gpu, "language": language}


def test_resolve_language_auto_variants():
    for value in (None, "", "auto", "AUTO", "  "):
        assert speech.resolve_language(value) == ("auto", None)


def test_resolve_language_explicit_codes_passed_through():
    # Not restricted to a fixed list; any short code is forwarded to whisper.
    for code in ("en", "pt", "es", "fr", "de", "it", "ar", "ja", "zh", "haw", "PT"):
        lang, error = speech.resolve_language(code)
        assert error is None and lang == code.lower()


def test_resolve_language_rejects_invalid_values():
    for bad in ("english", "e1", "12", "english language", "!!", 3):
        lang, error = speech.resolve_language(bad)
        assert lang is None and error


def test_build_command_defaults_to_auto_detection(tmp_path):
    cmd = speech.build_command(_cmd_cfg(tmp_path), "a.wav", "out", use_gpu=True)
    assert cmd[cmd.index("-l") + 1] == "auto"
    assert "-tr" not in cmd and "--translate" not in cmd  # never translate


def test_build_command_explicit_language(tmp_path):
    cmd = speech.build_command(_cmd_cfg(tmp_path, language="pt"), "a.wav", "out", use_gpu=True)
    assert cmd[cmd.index("-l") + 1] == "pt"
    assert "-tr" not in cmd and "--translate" not in cmd


def test_build_command_uses_custom_model_path(tmp_path):
    cfg = _cmd_cfg(tmp_path, model="ggml-large-v3.bin", language="en")
    cmd = speech.build_command(cfg, "a.wav", "out", use_gpu=False)
    assert cfg["whisper_model"] in cmd
    assert "-ng" in cmd  # CPU flag when gpu disabled


def test_transcribe_invalid_language_never_runs_whisper(monkeypatch, tmp_path):
    cfg = _cmd_cfg(tmp_path, language="english")

    def fail(*a, **k):
        raise AssertionError("whisper must not run for an invalid language")

    monkeypatch.setattr(speech, "_run_whisper", fail)
    text, error = speech.transcribe(cfg, "/tmp/a.wav")
    assert text == "" and "invalid language" in error
