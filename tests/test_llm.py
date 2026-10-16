from hyprwhispr import llm


def test_clean_answer_strips_think_block():
    assert llm.clean_answer("reasoning here\n</thinking>\nThe answer.") == "The answer."
    assert llm.clean_answer("<thinking>a</thinking>Real reply") == "Real reply"


def test_clean_answer_passthrough():
    assert llm.clean_answer("Just an answer.") == "Just an answer."
    assert llm.clean_answer(None) == ""


def test_run_pipeline_returns_plain_answer(monkeypatch):
    monkeypatch.setattr(llm, "ollama_chat", lambda cfg, messages, tools=None: {
        "message": {"content": "Hello there."}
    })
    assert llm.run_pipeline({"num_ctx": 1}, "hi") == "Hello there."


def test_run_pipeline_dispatches_tool(monkeypatch):
    calls = []

    def fake_dispatch(cfg, name, args):
        calls.append((name, args))
        return "opened the calculator"

    responses = iter([
        {"message": {"content": "", "tool_calls": [
            {"function": {"name": "open_app", "arguments": {"app": "calculator"}}}]}},
        {"message": {"content": "Done."}},
    ])
    monkeypatch.setattr(llm, "ollama_chat", lambda cfg, messages, tools=None: next(responses))
    monkeypatch.setattr(llm.tools, "dispatch_tool", fake_dispatch)

    assert llm.run_pipeline({"num_ctx": 1}, "open the calculator") == "Done."
    assert calls == [("open_app", {"app": "calculator"})]


def test_run_pipeline_empty_input():
    assert llm.run_pipeline({}, "   ") == "I didn't catch that."
