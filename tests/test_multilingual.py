"""Regression tests: the assistant must preserve the spoken language.

These use a scripted fake model, so they assert the *pipeline* (no English
normalization) rather than the model's translation quality. Fixed transcripts in
several languages stand in for real audio; a real model is only needed for the
manual integration procedure described in the docs.
"""

from hyprwhispr import llm, session

# Fixed transcripts (not an allow-list — just representative fixtures).
FIXTURES = {
    "pt": "abrir o firefox",
    "en": "open firefox",
    "es": "abre firefox",
    "de": "firefox öffnen",
}


def _text(text):
    return {"message": {"content": text}}


def _tool(name, **arguments):
    return {"message": {"content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}}


class RecordingModel:
    """Fake model that records the user message it was given."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.user_messages = []

    def __call__(self, cfg, messages, tools_schema=None):
        self.user_messages.append([m for m in messages if m["role"] == "user"][-1]["content"])
        return self.responses.pop(0) if self.responses else _text("done")


def test_transcripts_are_passed_unchanged_and_tools_still_work(monkeypatch):
    for language, transcript in FIXTURES.items():
        model = RecordingModel([_tool("open_app", app="Firefox"), _text("ok")])
        monkeypatch.setattr(llm, "ollama_chat", model)
        dispatched = []
        monkeypatch.setattr(llm.tools, "dispatch_tool",
                            lambda cfg, name, args: (dispatched.append((name, args)) or "opened Firefox"))
        llm.run_pipeline({}, transcript, state=session.new_state())
        # 1. the exact non-English text reaches the model (no translation step)
        assert model.user_messages[0] == transcript, language
        # 2. the unambiguous request still selects the existing tool
        assert dispatched == [("open_app", {"app": "Firefox"})], language


def test_no_translation_of_tool_arguments(monkeypatch):
    model = RecordingModel([_tool("open_app", app="firefox"), _text("ok")])
    monkeypatch.setattr(llm, "ollama_chat", model)
    captured = []
    monkeypatch.setattr(llm.tools, "dispatch_tool",
                        lambda cfg, name, args: (captured.append(args) or "opened"))
    llm.run_pipeline({}, "abrir o firefox", state=session.new_state())
    assert captured == [{"app": "firefox"}]  # argument passed through as-is


def test_system_prompt_requires_same_language_reply():
    assert "same language" in llm.SYSTEM_PROMPT
    assert "Do not translate" in llm.SYSTEM_PROMPT
