import json

from hyprwhispr import config, session


def test_new_state_shape():
    state = session.new_state()
    assert state["turns"] == []
    assert state["entities"] == {}
    assert state["pending"] is None


def test_append_turn_is_bounded():
    state = session.new_state()
    for i in range(50):
        session.append_turn(state, "user", f"message {i}", limit=3)
    assert len(state["turns"]) <= 6


def test_save_and_load_roundtrip():
    state = session.new_state()
    session.append_turn(state, "user", "open firefox", limit=6)
    session.save({}, state)
    loaded = session.load({})
    assert loaded["turns"][0]["content"] == "open firefox"


def test_expired_session_is_forgotten():
    state = session.new_state()
    session.append_turn(state, "user", "hello", limit=6)
    session.save({}, state)
    # rewrite the stored timestamp to the past (save() always stamps "now")
    path = config.STATE_DIR / "session.json"
    stored = json.loads(path.read_text())
    stored["updated"] = "2000-01-01T00:00:00"
    path.write_text(json.dumps(stored))
    loaded = session.load({"session_ttl_minutes": 30})
    assert loaded["turns"] == []


def test_entity_context_lists_target():
    state = session.new_state()
    state["entities"]["last_target"] = "Firefox"
    assert "Firefox" in session.entity_context(state)


def test_note_tool_extracts_open():
    state = session.new_state()
    session.note_tool(state, "open_app", {"app": "browser"}, "opened Firefox")
    assert state["entities"]["last_target"] == "Firefox"


def test_note_tool_extracts_game():
    state = session.new_state()
    session.note_tool(state, "launch_steam_game", {"game": "balatro"}, "launching the Steam game Balatro")
    assert state["entities"]["last_target"] == "Balatro"
    assert state["entities"]["last_game"] == "Balatro"


def test_note_tool_ignores_errors():
    state = session.new_state()
    session.note_tool(state, "open_app", {"app": "ghost"}, "error: no installed app matches 'ghost'")
    assert state["entities"] == {}


def test_note_tool_extracts_close_title():
    state = session.new_state()
    session.note_tool(state, "close_app", {"app": "steam"}, "closed 1 window(s): Steam")
    assert state["entities"]["last_target"] == "Steam"


def test_pending_options_appear_in_context():
    state = session.new_state()
    session.set_pending(state, ["Kate", "VSCodium"])
    assert "Kate" in session.entity_context(state)
    session.clear_pending(state)
    assert "Kate" not in session.entity_context(state)


def test_state_file_permissions():
    state = session.new_state()
    session.save({}, state)
    path = config.STATE_DIR / "session.json"
    assert path.exists()
    assert json.loads(path.read_text())["turns"] == []
