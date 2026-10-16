from hyprwhispr import config, memory


def test_save_and_list_notes():
    config.ensure_dirs()
    (config.NOTES_DIR / "notes.md").write_text("")
    memory.tool_save_note({}, "buy milk")
    assert "buy milk" in memory.tool_list_notes({}, "milk")
    assert memory.tool_list_notes({}, "nonexistent-token") in ("", "no matching notes")


def test_remember_and_recall_persist():
    memory.tool_remember({}, "colour", "green")
    assert memory.tool_recall({}, "colour").endswith("green")
    # recall through a fresh read of the on-disk preferences
    assert memory.load_preferences()["colour"] == "green"


def test_memory_context_includes_preferences():
    memory.tool_remember({}, "city", "Lisbon")
    assert "Lisbon" in memory.memory_context()


def test_recall_unknown_key():
    assert "nothing remembered" in memory.tool_recall({}, "does-not-exist")
