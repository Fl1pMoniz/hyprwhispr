"""Discovery for application/terminal/Steam/OpenCode launches. Fully mocked."""

import pytest

from hyprwhispr import apps, browsers, discovery


@pytest.fixture(autouse=True)
def _clear_cache():
    discovery.clear_cache()
    yield
    discovery.clear_cache()


def _firefox_index():
    return {"apps": [{"id": "firefox", "name": "Firefox", "generic": "Web Browser",
                      "keywords": ["browser"], "exec": "firefox %u", "terminal": False}]}


class Popen:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return object()


def test_configured_alias_missing_and_not_browser_is_reported(monkeypatch):
    cfg = {"apps": {"editor": "kitty -e nvim"}}
    monkeypatch.setattr(apps.shutil, "which", lambda name: None)
    result = apps.tool_open_app(cfg, "editor")
    assert result.startswith("error:") and "kitty" in result


def test_configured_browser_alias_missing_uses_discovered_browser(monkeypatch):
    cfg = {"apps": {"browser": "xdg-open https://duckduckgo.com"}, "search_url": "https://ddg/?q="}
    monkeypatch.setattr(apps.shutil, "which", lambda name: None)  # xdg-open missing
    monkeypatch.setattr(browsers, "select_browser",
                        lambda cfg, use_cache=True: discovery.Resolution(
                            requested="xdg-open", program="/usr/bin/firefox",
                            source="path", label="Firefox"))
    seen = {}
    monkeypatch.setattr(browsers, "launch_url",
                        lambda cfg, url, browser=None: seen.update(url=url) or "opened")
    result = apps.tool_open_app(cfg, "browser")
    assert result == "opened browser with Firefox"
    assert seen["url"] == "https://duckduckgo.com"  # reused the alias's URL


def test_configured_browser_alias_missing_and_no_browser(monkeypatch):
    cfg = {"apps": {"browser": "xdg-open https://duckduckgo.com"}}
    monkeypatch.setattr(apps.shutil, "which", lambda name: None)
    monkeypatch.setattr(browsers, "select_browser",
                        lambda cfg, use_cache=True: discovery.Resolution(source="none"))
    result = apps.tool_open_app(cfg, "browser")
    assert result.startswith("error:") and "browser" in result.lower()


def test_desktop_entry_with_missing_absolute_exec(monkeypatch):
    entry = {"id": "demo", "name": "Demo", "generic": "", "keywords": [],
             "exec": "/opt/gone/demo %u", "terminal": False}
    monkeypatch.setattr(apps, "load_app_index", lambda cfg: {"apps": [entry]})
    monkeypatch.setattr(apps, "load_steam_games", lambda cfg: {"games": []})
    monkeypatch.setattr(apps.shutil, "which", lambda name: None)  # no gtk-launch
    result = apps.tool_open_app({"apps": {}}, "Demo")
    assert result.startswith("error:") and "/opt/gone/demo" in result


def test_desktop_entry_launch_failure_is_reported(monkeypatch):
    monkeypatch.setattr(apps, "load_app_index", lambda cfg: _firefox_index())
    monkeypatch.setattr(apps, "load_steam_games", lambda cfg: {"games": []})
    monkeypatch.setattr(apps, "launch_desktop",
                        lambda cfg, entry: (_ for _ in ()).throw(RuntimeError("could not launch firefox")))
    result = apps.tool_open_app({"apps": {}}, "Firefox")
    assert result.startswith("error:") and "firefox" in result


def test_terminal_required_but_none_available(monkeypatch):
    entry = {"id": "htop", "name": "htop", "exec": "htop", "terminal": True}
    monkeypatch.setattr(apps.shutil, "which", lambda name: None)  # no gtk-launch
    monkeypatch.setattr(apps, "resolve_terminal",
                        lambda cfg: discovery.Resolution(source="none"))
    with pytest.raises(RuntimeError):
        apps.launch_desktop({"terminal_bin": "kitty"}, entry)


def test_terminal_required_uses_discovered_terminal(monkeypatch):
    entry = {"id": "htop", "name": "htop", "exec": "htop", "terminal": True}
    monkeypatch.setattr(apps.shutil, "which", lambda name: None)  # no gtk-launch
    monkeypatch.setattr(apps, "resolve_terminal",
                        lambda cfg: discovery.Resolution(program="/usr/bin/foot", source="path"))
    rec = Popen()
    monkeypatch.setattr(apps.subprocess, "Popen", rec)
    apps.launch_desktop({"terminal_bin": "kitty"}, entry)
    assert rec.calls[0][0] == ["/usr/bin/foot", "-e", "htop"]


def test_steam_missing_is_reported(monkeypatch):
    monkeypatch.setattr(apps, "load_steam_games",
                        lambda cfg: {"games": [{"appid": "1", "name": "Balatro"}]})
    monkeypatch.setattr(apps, "_steam_program", lambda cfg: None)
    result = apps.tool_launch_steam_game({"apps": {}}, "Balatro")
    assert result.startswith("error:") and "Steam" in result


def test_opencode_missing_is_reported(monkeypatch):
    monkeypatch.setattr(apps, "resolve_terminal",
                        lambda cfg: discovery.Resolution(program="/usr/bin/kitty", source="path"))
    monkeypatch.setattr(apps.discovery, "resolve_program",
                        lambda candidates, configured="", **kw: discovery.Resolution(source="none"))
    result = apps.tool_launch_opencode({"apps": {}}, "")
    assert result.startswith("error:") and "OpenCode" in result


def test_opencode_terminal_missing_is_reported(monkeypatch):
    monkeypatch.setattr(apps, "resolve_terminal",
                        lambda cfg: discovery.Resolution(source="none"))
    result = apps.tool_launch_opencode({"apps": {}}, "")
    assert result.startswith("error:") and "terminal" in result


def test_open_app_does_not_repeat_browser_discovery(monkeypatch):
    # a configured, available launcher must not trigger browser discovery at all
    cfg = {"apps": {"browser": "firefox https://duckduckgo.com"}}
    monkeypatch.setattr(apps.shutil, "which", lambda name: "/usr/bin/" + name)
    rec = Popen()
    monkeypatch.setattr(apps.subprocess, "Popen", rec)
    calls = {"n": 0}
    monkeypatch.setattr(browsers, "select_browser",
                        lambda cfg, use_cache=True: calls.__setitem__("n", calls["n"] + 1))
    assert apps.tool_open_app(cfg, "browser") == "opened browser"
    assert calls["n"] == 0
