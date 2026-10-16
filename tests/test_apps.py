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
