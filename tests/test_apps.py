from hyprwhispr import apps


def _index():
    return {"apps": [
        {"id": "kitty", "name": "kitty", "generic": "Terminal emulator", "keywords": ["terminal"], "exec": "kitty", "terminal": False},
        {"id": "firefox", "name": "Firefox", "generic": "Web Browser", "keywords": ["browser"], "exec": "firefox %u", "terminal": False},
        {"id": "thunar", "name": "Thunar File Manager", "generic": "File Manager", "keywords": ["files"], "exec": "thunar", "terminal": False},
        {"id": "thunar-settings", "name": "Thunar Preferences", "generic": "", "keywords": [], "exec": "thunar --settings", "terminal": False},
    ]}


def test_resolve_exact_id_beats_prefix():
    assert apps.resolve_app(_index(), "thunar")["name"] == "Thunar File Manager"


def test_resolve_by_generic():
    assert apps.resolve_app(_index(), "web browser")["name"] == "Firefox"


def test_resolve_empty_returns_none():
    assert apps.resolve_app(_index(), "") is None
    assert apps.resolve_app(_index(), "   ") is None


def test_resolve_unknown_returns_none():
    assert apps.resolve_app(_index(), "zzzz-not-here") is None


def test_resolve_steam_game():
    games = {"games": [{"appid": "367520", "name": "Hollow Knight"}, {"appid": "1", "name": "Balatro"}]}
    assert apps.resolve_game(games, "hollow")["appid"] == "367520"
    assert apps.resolve_game(games, "") is None


def test_exec_argv_strips_field_codes():
    assert apps._exec_argv("firefox %u") == ["firefox"]
    assert apps._exec_argv("env FOO=1 app %F --flag") == ["env", "FOO=1", "app", "--flag"]


def test_parse_desktop(tmp_path):
    path = tmp_path / "demo.desktop"
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Demo App\n"
        "GenericName=Demonstration\n"
        "Exec=demo %U\n"
        "Terminal=false\n"
    )
    data = apps._parse_desktop(path)
    assert data["Name"] == "Demo App"
    assert data["Exec"] == "demo %U"


def test_parse_desktop_ignores_non_application(tmp_path):
    path = tmp_path / "link.desktop"
    path.write_text("[Desktop Entry]\nType=Link\nName=Somewhere\n")
    assert apps._parse_desktop(path) is None


def test_normalize_folds_case_unicode_and_punctuation():
    assert apps.normalize("Firefox!") == "firefox"
    assert apps.normalize("  FIREFOX  ") == "firefox"
    assert apps.normalize("Ｆｉｒｅｆｏｘ") == "firefox"  # fullwidth -> NFKC
    assert apps.normalize("Visual-Studio_Code") == "visual studio code"


def _two_editors():
    return {"apps": [
        {"id": "kate", "name": "Kate", "generic": "Text Editor", "keywords": ["editor"], "exec": "kate", "terminal": False},
        {"id": "vscodium", "name": "VSCodium", "generic": "Text Editor", "keywords": ["editor"], "exec": "codium", "terminal": False},
    ]}


def test_resolve_candidates_are_ranked():
    candidates = apps.resolve_app_candidates(_index(), "firefox")
    assert candidates[0][1]["name"] == "Firefox"


def test_ambiguous_generic_query(monkeypatch):
    cfg = {"apps": {}, "app_ambiguity_margin": 150}
    monkeypatch.setattr(apps, "load_app_index", lambda cfg: _two_editors())
    monkeypatch.setattr(apps, "load_steam_games", lambda cfg: {"games": []})
    result = apps.tool_open_app(cfg, "editor")
    assert result.startswith(apps.AMBIGUOUS_PREFIX)
    assert apps.parse_ambiguous(result) == ["Kate", "VSCodium"]


def test_confident_query_not_ambiguous(monkeypatch):
    cfg = {"apps": {}, "app_ambiguity_margin": 150}
    monkeypatch.setattr(apps, "load_app_index", lambda cfg: _two_editors())
    monkeypatch.setattr(apps, "load_steam_games", lambda cfg: {"games": []})
    launched = {}
    monkeypatch.setattr(apps, "launch_desktop", lambda cfg, entry: launched.update(entry))
    assert apps.tool_open_app(cfg, "Kate") == "opened Kate"
    assert launched["id"] == "kate"


def test_configured_alias_used_before_index(monkeypatch):
    cfg = {"apps": {"browser": "firefox"}, "app_ambiguity_margin": 150}
    monkeypatch.setattr(apps.shutil, "which", lambda name: "/usr/bin/" + name)
    recorded = []
    monkeypatch.setattr(apps.subprocess, "Popen", lambda args, **kw: recorded.append(args))
    assert apps.tool_open_app(cfg, "my browser") == "opened my browser"
    assert recorded and recorded[0][0] == "firefox"


def test_unicode_and_punctuation_in_resolution():
    index = {"apps": [{"id": "firefox", "name": "Firefox", "generic": "Web Browser",
                       "keywords": ["browser"], "exec": "firefox", "terminal": False}]}
    assert apps.resolve_app(index, "Firefox!")["id"] == "firefox"
    assert apps.resolve_app(index, "  firefox  ")["id"] == "firefox"


def test_generic_reference_matches_single_app():
    index = {"apps": [{"id": "firefox", "name": "Firefox", "generic": "Web Browser",
                       "keywords": ["browser"], "exec": "firefox", "terminal": False}]}
    assert apps.resolve_app(index, "my web browser")["id"] == "firefox"
