"""Security-focused tests for the tool layer: confirmation gates, argument
validation and safe defaults. These use mocks, never the real desktop.
"""

from types import SimpleNamespace

import pytest

from hyprwhispr import apps, config, system_actions, web


class Recorder:
    """Captures subprocess calls without running anything."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def Popen(self, args, **kwargs):
        self.calls.append(("Popen", args))
        return SimpleNamespace(pid=1234, returncode=0, wait=lambda timeout=None: 0)

    def run(self, args, **kwargs):
        self.calls.append(("run", args))
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def _cfg():
    return config.load_config()


# --- run_shell ---------------------------------------------------------------

def test_run_shell_requires_confirmation(monkeypatch):
    monkeypatch.setattr(system_actions, "confirm", lambda *a, **k: False)
    rec = Recorder()
    monkeypatch.setattr(system_actions.subprocess, "run", rec.run)
    result = system_actions.tool_run_shell(_cfg(), "echo hi")
    assert "denied" in result
    assert rec.calls == []


def test_run_shell_runs_when_approved(monkeypatch):
    monkeypatch.setattr(system_actions, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(system_actions.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="hi\n", stderr=""))
    assert system_actions.tool_run_shell(_cfg(), "echo hi").startswith("exit 0")


# --- install_package ---------------------------------------------------------

def test_install_package_requires_confirmation(monkeypatch):
    monkeypatch.setattr(system_actions, "confirm", lambda *a, **k: False)
    rec = Recorder()
    monkeypatch.setattr(system_actions.subprocess, "Popen", rec.Popen)
    result = system_actions.tool_install_package(_cfg(), "htop")
    assert "denied" in result
    assert rec.calls == []


def test_install_package_rejects_metacharacters(monkeypatch):
    monkeypatch.setattr(system_actions, "confirm", lambda *a, **k: True)
    rec = Recorder()
    monkeypatch.setattr(system_actions.subprocess, "Popen", rec.Popen)
    result = system_actions.tool_install_package(_cfg(), "htop; rm -rf /")
    assert result.startswith("error:")
    assert rec.calls == []


def test_install_package_launches_dnf_when_approved(monkeypatch):
    monkeypatch.setattr(system_actions, "confirm", lambda *a, **k: True)
    rec = Recorder()
    monkeypatch.setattr(system_actions.subprocess, "Popen", rec.Popen)
    system_actions.tool_install_package(_cfg(), "htop")
    assert any(call[0] == "Popen" and "dnf" in call[1] and "sudo" in call[1] for call in rec.calls)


# --- delete_path -------------------------------------------------------------

def test_delete_path_requires_confirmation(monkeypatch, tmp_path):
    victim = tmp_path / "file.txt"
    victim.write_text("data")
    monkeypatch.setattr(system_actions, "confirm", lambda *a, **k: False)
    rec = Recorder()
    monkeypatch.setattr(system_actions.subprocess, "run", rec.run)
    assert "denied" in system_actions.tool_delete_path(_cfg(), str(victim))
    assert victim.exists()
    assert rec.calls == []


def test_delete_path_trashes_when_approved(monkeypatch, tmp_path):
    victim = tmp_path / "file.txt"
    victim.write_text("data")
    monkeypatch.setattr(system_actions, "confirm", lambda *a, **k: True)
    rec = Recorder(returncode=0)
    monkeypatch.setattr(system_actions.subprocess, "run", rec.run)
    system_actions.tool_delete_path(_cfg(), str(victim))
    assert any(call[0] == "run" and "gio" in call[1] for call in rec.calls)


def test_delete_path_rejects_missing_file(monkeypatch, tmp_path):
    assert system_actions.tool_delete_path(_cfg(), str(tmp_path / "nope")).startswith("error:")


# --- open_app ----------------------------------------------------------------

def test_open_app_rejects_empty_name(monkeypatch):
    monkeypatch.setattr(apps, "load_app_index", lambda cfg: {"apps": []})
    monkeypatch.setattr(apps, "load_steam_games", lambda cfg: {"games": []})
    assert apps.tool_open_app(_cfg(), "").startswith("error:")


def test_open_app_unknown_name(monkeypatch):
    monkeypatch.setattr(apps, "load_app_index", lambda cfg: {"apps": []})
    monkeypatch.setattr(apps, "load_steam_games", lambda cfg: {"games": []})
    assert apps.tool_open_app(_cfg(), "definitely-not-an-app").startswith("error:")


def test_open_app_uses_configured_alias(monkeypatch):
    cfg = _cfg()
    cfg["apps"] = {"terminal": "kitty"}
    monkeypatch.setattr(apps.shutil, "which", lambda name: "/usr/bin/" + name)
    rec = Recorder()
    monkeypatch.setattr(apps.subprocess, "Popen", rec.Popen)
    assert apps.tool_open_app(cfg, "terminal") == "opened terminal"
    assert any(call[0] == "Popen" and call[1][0] == "kitty" for call in rec.calls)


# --- web_search --------------------------------------------------------------

def test_web_search_url_encodes_query(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(web.subprocess, "Popen", rec.Popen)
    monkeypatch.setattr(web, "notify", lambda *a, **k: None)
    cfg = _cfg()
    cfg["search_url"] = "https://example.com/?q="
    web.tool_web_search(cfg, "a b&c")
    assert any(call[0] == "Popen" and "a+b%26c" in call[1][1] for call in rec.calls)


# --- local-first default -----------------------------------------------------

def test_ollama_endpoint_is_loopback_by_default():
    import urllib.parse
    host = urllib.parse.urlparse(config.DEFAULTS["ollama_url"]).hostname
    assert host in ("127.0.0.1", "localhost", "::1")
