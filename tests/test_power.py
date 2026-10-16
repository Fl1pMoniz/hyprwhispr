"""Power (on/off) control and safe model release. Mocks only.

No Ollama server, microphone or real unloading is involved: the Ollama API and
subprocesses are mocked. The isolated config/data dir from conftest is reused.
"""

import json
import subprocess

import pytest

from hyprwhispr import audio, cli, config, llm, power, wakeword


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return path


def _disk(path):
    return json.loads(path.read_text())


# --- activation default / compatibility --------------------------------------

def test_default_is_enabled():
    assert config.DEFAULTS["enabled"] is True
    assert config.is_enabled({}) is True
    assert config.is_enabled({"enabled": None}) is True
    assert config.is_enabled({"enabled": False}) is False
    assert config.is_enabled({"enabled": "off"}) is False
    assert config.is_enabled({"enabled": "yes"}) is True


def test_existing_config_without_enabled_stays_enabled(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"model": "qwen3:4b"}))
    cfg = config.load_config(path)
    assert config.is_enabled(cfg) is True


# --- config update safety -----------------------------------------------------

def test_update_config_preserves_other_keys(config_path):
    config.update_config({"model": "qwen3:8b", "enabled": True}, config_path)
    config.update_config({"enabled": False}, config_path)
    data = _disk(config_path)
    assert data["model"] == "qwen3:8b" and data["enabled"] is False


def test_update_config_recovers_from_malformed_file(config_path):
    config_path.write_text("{not valid json")
    config.update_config({"enabled": True}, config_path)
    assert _disk(config_path) == {"enabled": True}


# --- recording-active helper (stale state) ------------------------------------

def test_recording_active_handles_missing_and_stale(monkeypatch, tmp_path):
    pidfile = tmp_path / "record.pid"
    monkeypatch.setattr(config, "PIDFILE", pidfile)
    assert power.recording_active() is False          # missing
    pidfile.write_text("not-a-pid")
    assert power.recording_active() is False          # garbage
    child = subprocess.Popen(["sh", "-c", "exit 0"])
    child.wait()                                       # now reaped -> stale pid
    pidfile.write_text(str(child.pid))
    assert power.recording_active() is False          # stale
    pidfile.write_text(str(__import__("os").getpid()))
    assert power.recording_active() is True           # our own live process


# --- power status -------------------------------------------------------------

def test_power_status_reports_enabled(config_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "loaded_models", lambda cfg: [])
    config.update_config({"enabled": True, "model": "qwen3:4b"}, config_path)
    assert cli.main(["power", "status"]) == 0
    out = capsys.readouterr().out
    assert "enabled: yes" in out
    assert "keep-alive policy" in out and "model:" in out  # reused model status

    config.update_config({"enabled": False}, config_path)
    assert cli.main(["power", "status"]) == 0
    assert "enabled: no" in capsys.readouterr().out


def test_power_status_available_while_disabled(config_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "loaded_models", lambda cfg: [])
    config.update_config({"enabled": False, "model": "qwen3:4b"}, config_path)
    assert cli.main(["power", "status"]) == 0
    assert "enabled: no" in capsys.readouterr().out


# --- power on -----------------------------------------------------------------

def test_power_on_enables_without_loading_model(config_path, monkeypatch, capsys):
    config.update_config({"enabled": False, "model": "qwen3:4b"}, config_path)
    calls = []
    monkeypatch.setattr(llm, "ollama_chat", lambda *a, **k: calls.append("chat"))
    monkeypatch.setattr(llm, "unload_model", lambda *a, **k: calls.append("unload"))
    assert cli.main(["power", "on"]) == 0
    assert _disk(config_path)["enabled"] is True
    assert calls == []
    assert "not loaded" in capsys.readouterr().out


def test_power_on_is_idempotent(config_path, monkeypatch, capsys):
    config.update_config({"enabled": True, "model": "qwen3:4b"}, config_path)
    assert cli.main(["power", "on"]) == 0
    assert "already on" in capsys.readouterr().out


# --- power off ----------------------------------------------------------------

def test_power_off_disables_and_refuses_requests(config_path, monkeypatch, capsys):
    config.update_config({"enabled": True, "model": "qwen3:4b"}, config_path)
    monkeypatch.setattr(power, "recording_active", lambda: False)
    monkeypatch.setattr(cli, "loaded_models", lambda cfg: [])
    unloaded = []
    monkeypatch.setattr(power, "unload_if_idle",
                        lambda cfg, model=None: (unloaded.append(model) or (True, "unloaded")))
    assert cli.main(["power", "off"]) == 0
    assert _disk(config_path)["enabled"] is False
    assert unloaded == [None]  # unload_if_idle(cfg) called once
    capsys.readouterr()
    # a new request must be refused without touching the model
    monkeypatch.setattr(cli, "run_pipeline",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("model was called")))
    assert cli.main(["ask", "hello"]) == 1
    assert "off" in capsys.readouterr().out.lower()


def test_power_off_is_idempotent(config_path, monkeypatch, capsys):
    config.update_config({"enabled": False, "model": "qwen3:4b"}, config_path)
    monkeypatch.setattr(power, "recording_active", lambda: False)
    monkeypatch.setattr(power, "unload_if_idle", lambda cfg, model=None: (True, "unloaded"))
    assert cli.main(["power", "off"]) == 0
    assert "already off" in capsys.readouterr().out


# --- safe unload (power.unload_if_idle) --------------------------------------

def test_unload_if_idle_unloads_when_idle(monkeypatch):
    unloaded = []
    monkeypatch.setattr(power, "recording_active", lambda: False)
    monkeypatch.setattr(power.llm, "unload_model",
                        lambda cfg, model=None: (unloaded.append(model) or (True, None)))
    monkeypatch.setattr(power.llm, "loaded_models", lambda cfg: [])
    ok, message = power.unload_if_idle({"model": "qwen3:4b"})
    assert ok and "qwen3:4b" in message and unloaded == ["qwen3:4b"]


def test_unload_if_idle_reports_failure(monkeypatch):
    monkeypatch.setattr(power, "recording_active", lambda: False)
    monkeypatch.setattr(power.llm, "unload_model", lambda cfg, model=None: (False, "boom"))
    ok, message = power.unload_if_idle({"model": "qwen3:4b"})
    assert not ok and "boom" in message


def test_unload_if_idle_reports_unverifiable(monkeypatch):
    monkeypatch.setattr(power, "recording_active", lambda: False)
    monkeypatch.setattr(power.llm, "unload_model", lambda cfg, model=None: (True, None))
    monkeypatch.setattr(power.llm, "loaded_models", lambda cfg: None)  # API unreachable
    ok, message = power.unload_if_idle({"model": "qwen3:4b"})
    assert ok and "could not be reached" in message


def test_unload_if_idle_does_not_interrupt_recording(monkeypatch):
    called = []
    monkeypatch.setattr(power, "recording_active", lambda: True)
    monkeypatch.setattr(power.llm, "unload_model",
                        lambda *a, **k: called.append(1) or (True, None))
    ok, message = power.unload_if_idle({"model": "qwen3:4b"})
    assert not ok and "recording" in message and called == []


def test_power_off_leaves_model_when_recording_active(config_path, monkeypatch, capsys):
    config.update_config({"enabled": True, "model": "qwen3:4b"}, config_path)
    monkeypatch.setattr(power, "recording_active", lambda: True)
    monkeypatch.setattr(cli, "_wait_for_recording_to_finish", lambda timeout=3.0: False)
    called = []
    monkeypatch.setattr(power, "unload_if_idle",
                        lambda cfg, model=None: called.append(model) or (True, "unloaded"))
    assert cli.main(["power", "off"]) == 0
    assert called == []
    assert "recording is still in progress" in capsys.readouterr().out


def test_power_off_reports_failed_unload(config_path, monkeypatch, capsys):
    config.update_config({"enabled": True, "model": "qwen3:4b"}, config_path)
    monkeypatch.setattr(power, "recording_active", lambda: False)
    monkeypatch.setattr(power, "unload_if_idle", lambda cfg, model=None: (False, "boom"))
    monkeypatch.setattr(cli, "loaded_models", lambda cfg: [])
    assert cli.main(["power", "off"]) == 0
    assert "boom" in capsys.readouterr().out


# --- unload happens after the whole turn -------------------------------------

def test_unload_runs_after_the_complete_turn(config_path, monkeypatch):
    order = []
    monkeypatch.setattr(cli, "run_pipeline",
                        lambda cfg, text, state=None: order.append("pipeline") or "ok")
    monkeypatch.setattr(cli, "_unload_after_turn", lambda cfg: order.append("unload"))
    cli._run_turn({"enabled": True, "keep_alive": "0"}, "hello")
    assert order == ["pipeline", "unload"]


# --- recording / wake-word respect the disabled state ------------------------

def test_record_start_refuses_when_disabled(monkeypatch):
    called = []
    monkeypatch.setattr(audio.subprocess, "Popen", lambda *a, **k: called.append(1))
    monkeypatch.setattr(audio, "notify", lambda *a, **k: None)
    assert audio.record_start({"enabled": False}) == 1
    assert called == []


def test_wake_word_listen_refuses_when_disabled(config_path):
    config.update_config({"enabled": False, "wake_word_mode": "both"}, config_path)
    cfg = config.load_config()
    with pytest.raises(wakeword.WakeWordError):
        wakeword.run_listen(cfg, lambda c, wav: None)


def test_cli_listen_refuses_when_disabled(config_path, capsys):
    config.update_config({"enabled": False}, config_path)
    assert cli.main(["listen", "1"]) == 1
    assert "off" in capsys.readouterr().out.lower()
