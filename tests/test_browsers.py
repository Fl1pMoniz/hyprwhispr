"""Browser discovery and safe URL opening. No real browser is launched."""

import pytest

from hyprwhispr import browsers, discovery


@pytest.fixture(autouse=True)
def _clear_cache():
    discovery.clear_cache()
    yield
    discovery.clear_cache()


class Popen:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return object()


def _which(available):
    """Return a fake shutil.which that only finds names in *available*."""
    def fake(name):
        return f"/usr/bin/{name}" if name in available else None
    return fake


def test_preferred_browser_is_selected(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", _which({"chromium"}))
    rec = Popen()
    monkeypatch.setattr(browsers.subprocess, "Popen", rec)
    cfg = {"browser_bin": "chromium", "search_url": "https://x/?q="}
    result = browsers.launch_url(cfg, "https://example.com")
    assert "Chromium" in result and result.startswith("opened")
    assert rec.calls[0][0] == ["/usr/bin/chromium", "https://example.com"]


def test_missing_preferred_falls_back_to_alternative(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", _which({"firefox"}))
    rec = Popen()
    monkeypatch.setattr(browsers.subprocess, "Popen", rec)
    cfg = {"browser_bin": "brave", "search_url": "https://x/?q="}
    res = browsers.select_browser(cfg)
    assert res.found and res.used_alternative and res.source == "path"
    # the caller can mention the fallback
    assert "brave" in browsers.no_browser_message(res) or res.requested == "brave"


def test_no_browser_available_reports_clearly(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", _which(set()))
    cfg = {"browser_bin": ""}
    res = browsers.select_browser(cfg)
    assert not res.found
    message = browsers.no_browser_message(res)
    assert message.startswith("error:") and "browser" in message.lower()


def test_configured_path_invalid_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery.shutil, "which", _which({"firefox"}))
    cfg = {"browser_bin": str(tmp_path / "does-not-exist")}
    res = browsers.select_browser(cfg)
    assert res.found and res.source == "path" and res.used_alternative


def test_launch_failure_is_reported(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", _which({"firefox"}))
    monkeypatch.setattr(browsers.subprocess, "Popen",
                        lambda argv, **kw: (_ for _ in ()).throw(OSError("boom")))
    result = browsers.launch_url({"browser_bin": ""}, "https://example.com")
    assert result.startswith("error:") and "boom" in result


def test_launch_uses_argv_not_shell(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", _which({"firefox"}))
    rec = Popen()
    monkeypatch.setattr(browsers.subprocess, "Popen", rec)
    browsers.launch_url({"browser_bin": ""}, "https://example.com/?q=a b&c")
    argv, kwargs = rec.calls[0]
    assert isinstance(argv, list)
    assert kwargs.get("shell") is not True
    assert "https://example.com/?q=a b&c" in argv  # passed as one element, never split


def test_generic_opener_fallback_syntax(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", _which({"xdg-open"}))
    rec = Popen()
    monkeypatch.setattr(browsers.subprocess, "Popen", rec)
    result = browsers.launch_url({"browser_bin": ""}, "https://example.com")
    assert rec.calls[0][0] == ["/usr/bin/xdg-open", "https://example.com"]
    assert "xdg-open" in result


def test_gio_fallback_uses_open_subcommand(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", _which({"gio"}))
    rec = Popen()
    monkeypatch.setattr(browsers.subprocess, "Popen", rec)
    browsers.launch_url({"browser_bin": ""}, "https://example.com")
    assert rec.calls[0][0] == ["/usr/bin/gio", "open", "https://example.com"]


def test_open_browser_without_url(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", _which({"firefox"}))
    rec = Popen()
    monkeypatch.setattr(browsers.subprocess, "Popen", rec)
    assert browsers.open_browser({"browser_bin": ""}).startswith("opened")
    assert rec.calls[0][0] == ["/usr/bin/firefox"]


def test_open_browser_generic_opener_uses_home_url(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", _which({"xdg-open"}))
    rec = Popen()
    monkeypatch.setattr(browsers.subprocess, "Popen", rec)
    browsers.open_browser({"browser_bin": "", "search_url": "https://duckduckgo.com/?q="})
    assert rec.calls[0][0] == ["/usr/bin/xdg-open", "https://duckduckgo.com/"]
