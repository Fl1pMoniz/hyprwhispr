from hyprwhispr import llm


def test_clean_answer_strips_think_block():
    assert llm.clean_answer("reasoning here\n</thinking>\nThe answer.") == "The answer."
    assert llm.clean_answer("<thinking>a</thinking>Real reply") == "Real reply"


def test_clean_answer_passthrough():
    assert llm.clean_answer("Just an answer.") == "Just an answer."
    assert llm.clean_answer(None) == ""


def test_clean_answer_strips_leaked_tool_call():
    # a model that echoes a tool call as text must not leak raw JSON to the user
    assert llm.clean_answer('<tool_call>{"name": "open_app", "arguments": {}}</tool_call>') == ""
    assert llm.clean_answer('Opened. <tool_call>{"name": "x"}</tool_call>') == "Opened."
    assert llm.clean_answer('<tool_call>{"name": "x", "arguments": {}}') == ""


def test_clean_answer_blanks_bare_tool_envelope():
    assert llm.clean_answer('{"name": "open_app", "arguments": {"app": "x"}}') == ""
    assert llm.clean_answer('{"tool": "web_search", "arguments": {"query": "x"}}') == ""
    # prose that merely contains JSON is left intact
    assert llm.clean_answer('The answer is {"temperature": 20}.') == 'The answer is {"temperature": 20}.'
    # JSON naming an unknown tool is not a tool envelope
    assert llm.clean_answer('{"name": "not_a_tool"}') == '{"name": "not_a_tool"}'


def test_parse_tool_json_accepts_tool_call_block():
    calls = llm.parse_tool_json('<tool_call>{"name": "open_app", "arguments": {"app": "Firefox"}}</tool_call>')
    assert calls == [{"function": {"name": "open_app", "arguments": {"app": "Firefox"}}}]


def test_parse_tool_json_accepts_multiple_tool_calls():
    content = ('<tool_call>{"name": "open_app", "arguments": {"app": "a"}}</tool_call>'
               '<tool_call>{"name": "close_app", "arguments": {"app": "b"}}</tool_call>')
    calls = llm.parse_tool_json(content)
    assert [c["function"]["name"] for c in calls] == ["open_app", "close_app"]


def test_parse_tool_json_accepts_fenced_and_whole_object():
    assert llm.parse_tool_json('```json\n{"tool": "list_apps", "arguments": {}}\n```')[0]["function"]["name"] == "list_apps"
    assert llm.parse_tool_json('{"tool": "list_apps", "arguments": {}}')[0]["function"]["name"] == "list_apps"


def test_parse_tool_json_accepts_unclosed_block():
    calls = llm.parse_tool_json('<tool_call>{"name": "open_app", "arguments": {"app": "Firefox"}}')
    assert calls and calls[0]["function"]["name"] == "open_app"


def test_parse_tool_json_never_executes_from_prose():
    assert llm.parse_tool_json('You could call {"name": "open_app", "arguments": {"app": "x"}} to run it.') == []
    assert llm.parse_tool_json("The weather is nice today.") == []
    assert llm.parse_tool_json('The config is {"a": 1}.') == []


def test_parse_tool_json_malformed_returns_empty():
    assert llm.parse_tool_json('<tool_call>{"name": "open_app", "arguments": </tool_call>') == []
    assert llm.parse_tool_json('<tool_call>not json</tool_call>') == []
    assert llm.parse_tool_json(None) == []


def test_ollama_chat_optionally_caps_generated_tokens(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm, "http_json",
                        lambda url, payload, timeout=120: captured.update(payload) or {"message": {}})
    base = {"ollama_url": "http://x", "model": "m"}
    llm.ollama_chat({**base, "max_tokens": 256}, [])
    assert captured["options"]["num_predict"] == 256
    captured.clear()
    llm.ollama_chat(base, [])
    assert "num_predict" not in captured["options"]  # no cap by default


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
