"""Model-lifetime controls: keep-alive validation, /api/ps parsing and unload.

Everything here is mocked; no Ollama server, model weights or GPU are touched.
"""

import json
import urllib.error

from hyprwhispr import cli, config, llm, session


def test_keep_alive_variants_normalise():
    assert config.validate_keep_alive("auto") == ("5m", None)
    assert config.validate_keep_alive("") == ("5m", None)
    assert config.validate_keep_alive("always") == ("-1", None)
    assert config.validate_keep_alive("0") == ("0", None)
    assert config.validate_keep_alive("10m") == ("10m", None)
    assert config.validate_keep_alive("1h") == ("1h", None)
    assert config.validate_keep_alive("-1") == ("-1", None)


def test_keep_alive_rejects_junk():
    value, error = config.validate_keep_alive("soon")
    assert value is None and "invalid keep-alive" in error
    assert config.validate_keep_alive(True)[0] is None


def test_keep_alive_policy_labels():
    assert "always" in config.keep_alive_policy("-1")
    assert "unload" in config.keep_alive_policy("0")
    assert "5m" in config.keep_alive_policy("5m")


def test_loaded_models_parses_api_ps(monkeypatch):
    monkeypatch.setattr(llm, "http_get_json", lambda url, timeout=10: {"models": [
        {"name": "qwen3:4b", "size": 1024, "size_vram": 2048, "expires_at": "soon"}]})
    models = llm.loaded_models({"ollama_url": "http://x"})
    assert models[0]["name"] == "qwen3:4b" and models[0]["size_vram"] == 2048


def test_loaded_models_reports_unreachable(monkeypatch):
    def boom(url, timeout=10):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(llm, "http_get_json", boom)
    assert llm.loaded_models({"ollama_url": "http://x"}) is None


def test_unload_model_sends_keep_alive_zero(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm, "http_json",
                        lambda url, payload, timeout=120: captured.update(payload) or {})
    ok, error = llm.unload_model({"ollama_url": "http://x", "model": "qwen3:4b"})
    assert ok and error is None
    assert captured["keep_alive"] == 0 and captured["model"] == "qwen3:4b"


def test_unload_model_reports_failure(monkeypatch):
    monkeypatch.setattr(llm, "http_json",
                        lambda url, payload, timeout=120: (_ for _ in ()).throw(urllib.error.URLError("refused")))
    ok, error = llm.unload_model({"ollama_url": "http://x", "model": "qwen3:4b"})
    assert not ok and "reachable" in error


def _run_cli(monkeypatch, tmp_path, argv):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.save_config(dict(config.DEFAULTS), tmp_path / "config.json")
    return cli.main(argv)


def test_cli_model_status_shows_policy_and_loaded(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "loaded_models", lambda cfg: [
        {"name": "qwen3:4b", "size": 100, "size_vram": 2048, "expires_at": "2026"}])
    assert _run_cli(monkeypatch, tmp_path, ["model", "status"]) == 0
    out = capsys.readouterr().out
    assert "model: qwen3:4b" in out and "keep-alive policy" in out and "loaded: yes" in out


def test_cli_model_status_when_ollama_down(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "loaded_models", lambda cfg: None)
    assert _run_cli(monkeypatch, tmp_path, ["model", "status"]) == 1
    assert "not reachable" in capsys.readouterr().out


def test_cli_model_keep_alive_persists(monkeypatch, tmp_path, capsys):
    assert _run_cli(monkeypatch, tmp_path, ["model", "keep-alive", "always"]) == 0
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["keep_alive"] == "-1"
    assert "always" in capsys.readouterr().out


def test_cli_model_keep_alive_rejects_bad_value(monkeypatch, tmp_path, capsys):
    assert _run_cli(monkeypatch, tmp_path, ["model", "keep-alive", "soon"]) == 2
    assert "invalid keep-alive" in capsys.readouterr().out


def test_cli_model_unload_verifies(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "unload_model", lambda cfg, model=None: (True, None))
    monkeypatch.setattr(cli, "loaded_models", lambda cfg: [])  # nothing loaded afterwards
    monkeypatch.setattr(cli, "_recording_active", lambda: False)
    assert _run_cli(monkeypatch, tmp_path, ["model", "unload"]) == 0
    assert "unloaded" in capsys.readouterr().out


def test_cli_model_unload_refuses_while_recording(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "_recording_active", lambda: True)
    monkeypatch.setattr(cli, "unload_model", lambda cfg, model=None: (True, None))
    assert _run_cli(monkeypatch, tmp_path, ["model", "unload"]) == 1
    assert "recording is in progress" in capsys.readouterr().out


def test_cli_model_alias_still_sets_model(monkeypatch, tmp_path, capsys):
    assert _run_cli(monkeypatch, tmp_path, ["model", "large"]) == 0
    assert json.loads((tmp_path / "config.json").read_text())["model"] == "qwen3:8b"


def test_turn_keep_alive_never_zero():
    assert config.turn_keep_alive("0") == "5m"
    assert config.turn_keep_alive("none") == "5m"
    assert config.turn_keep_alive("auto") == "5m"
    assert config.turn_keep_alive(None) == "5m"
    assert config.turn_keep_alive("10m") == "10m"
    assert config.turn_keep_alive("-1") == "-1"


def test_keep_alive_is_unload():
    assert config.keep_alive_is_unload("0") is True
    assert config.keep_alive_is_unload("5m") is False
    assert config.keep_alive_is_unload(None) is False


def _two_step_model(seen):
    responses = [
        {"message": {"content": "", "tool_calls": [
            {"function": {"name": "open_app", "arguments": {"app": "Firefox"}}}]}},
        {"message": {"content": "Opened."}},
    ]

    def fake(cfg, messages, tool_schema=None):
        seen.append(cfg.get("keep_alive"))
        return responses.pop(0)

    return fake


def test_multistep_turn_never_sends_zero_keep_alive(monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "ollama_chat", _two_step_model(seen))
    monkeypatch.setattr(llm.tools, "dispatch_tool", lambda cfg, name, args: "opened Firefox")
    state = session.new_state()
    llm.run_pipeline({"keep_alive": "0"}, "open firefox", state=state)
    assert seen and all(value == "5m" for value in seen)  # never zero mid-turn


def test_multistep_turn_honours_nonzero_policy(monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "ollama_chat", _two_step_model(seen))
    monkeypatch.setattr(llm.tools, "dispatch_tool", lambda cfg, name, args: "opened Firefox")
    llm.run_pipeline({"keep_alive": "10m"}, "open firefox", state=session.new_state())
    assert seen and all(value == "10m" for value in seen)


def test_run_turn_unloads_after_turn_when_policy_zero(monkeypatch):
    recorded = []
    monkeypatch.setattr(cli, "run_pipeline", lambda cfg, text, state=None: "done")
    monkeypatch.setattr(cli, "_recording_active", lambda: False)
    monkeypatch.setattr(cli, "unload_model", lambda cfg, model=None: (recorded.append(cfg) or (True, None)))
    cli._run_turn({"keep_alive": "0"}, "hello")
    assert recorded  # unloaded after the whole turn


def test_run_turn_does_not_unload_for_nonzero_policy(monkeypatch):
    recorded = []
    monkeypatch.setattr(cli, "run_pipeline", lambda cfg, text, state=None: "done")
    monkeypatch.setattr(cli, "_recording_active", lambda: False)
    monkeypatch.setattr(cli, "unload_model", lambda cfg, model=None: (recorded.append(cfg) or (True, None)))
    cli._run_turn({"keep_alive": "5m"}, "hello")
    assert recorded == []


def test_run_turn_skips_unload_while_recording(monkeypatch):
    recorded = []
    monkeypatch.setattr(cli, "run_pipeline", lambda cfg, text, state=None: "done")
    monkeypatch.setattr(cli, "_recording_active", lambda: True)
    monkeypatch.setattr(cli, "unload_model", lambda cfg, model=None: (recorded.append(cfg) or (True, None)))
    cli._run_turn({"keep_alive": "0"}, "hello")
    assert recorded == []
