"""Agent-loop tests using a scripted fake model. No model or desktop is touched."""

from hyprwhispr import apps, llm, session


def text_response(text):
    return {"message": {"content": text}}


def tool_response(name, **arguments):
    return {"message": {"content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}}


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, cfg, messages, tools_schema=None):
        self.calls.append((messages, tools_schema))
        if self.responses:
            return self.responses.pop(0)
        return text_response("done")


def patch_dispatch(monkeypatch, result="ok"):
    calls = []

    def fake(cfg, name, arguments):
        calls.append((name, arguments))
        return result

    monkeypatch.setattr(llm.tools, "dispatch_tool", fake)
    return calls


def test_plain_answer_runs_no_tools(monkeypatch):
    monkeypatch.setattr(llm, "ollama_chat", FakeModel([text_response("Paris.")]))
    calls = patch_dispatch(monkeypatch)
    assert llm.run_pipeline({}, "What is the capital of France?") == "Paris."
    assert calls == []


def test_tool_call_then_answer_records_entity(monkeypatch):
    model = FakeModel([tool_response("open_app", app="Firefox"), text_response("Opened Firefox.")])
    monkeypatch.setattr(llm, "ollama_chat", model)
    calls = patch_dispatch(monkeypatch, result="opened Firefox")
    state = session.new_state()
    answer = llm.run_pipeline({}, "open firefox", state=state)
    assert answer == "Opened Firefox."
    assert calls == [("open_app", {"app": "Firefox"})]
    assert state["entities"]["last_target"] == "Firefox"


def test_duplicate_tool_call_is_suppressed(monkeypatch):
    model = FakeModel([
        tool_response("open_app", app="Firefox"),
        tool_response("open_app", app="Firefox"),
        text_response("Opened."),
    ])
    monkeypatch.setattr(llm, "ollama_chat", model)
    calls = patch_dispatch(monkeypatch, result="opened Firefox")
    assert llm.run_pipeline({}, "open firefox") == "Opened."
    assert len(calls) == 1  # executed once only


def test_unknown_tool_is_reported_not_executed(monkeypatch):
    model = FakeModel([tool_response("frobnicate"), text_response("I can't do that.")])
    monkeypatch.setattr(llm, "ollama_chat", model)
    # use the real dispatcher here: it must reject the unknown tool safely
    assert llm.run_pipeline({}, "frobnicate the widget") == "I can't do that."


def test_malformed_arguments_are_coerced_to_empty(monkeypatch):
    model = FakeModel([
        {"message": {"content": "", "tool_calls": [{"function": {"name": "open_app", "arguments": "not json"}}]}},
        text_response("ok"),
    ])
    monkeypatch.setattr(llm, "ollama_chat", model)
    calls = patch_dispatch(monkeypatch)
    llm.run_pipeline({}, "open something")
    assert calls == [("open_app", {})]


def test_json_tool_fallback(monkeypatch):
    json_tool = '{"tool": "open_app", "arguments": {"app": "Firefox"}}'
    model = FakeModel([text_response(json_tool), text_response("Opened.")])
    monkeypatch.setattr(llm, "ollama_chat", model)
    calls = patch_dispatch(monkeypatch, result="opened Firefox")
    assert llm.run_pipeline({}, "open firefox") == "Opened."
    assert calls == [("open_app", {"app": "Firefox"})]


def test_plain_text_is_not_mistaken_for_a_tool_call(monkeypatch):
    # a normal answer that happens to contain JSON must not trigger a tool
    model = FakeModel([text_response('The config is {"a": 1} in the file.')])
    monkeypatch.setattr(llm, "ollama_chat", model)
    calls = patch_dispatch(monkeypatch)
    llm.run_pipeline({}, "show the config")
    assert calls == []


def test_step_budget_then_forced_answer(monkeypatch):
    model = FakeModel([tool_response("list_apps", query="a"), tool_response("list_apps", query="b")])
    monkeypatch.setattr(llm, "ollama_chat", model)
    patch_dispatch(monkeypatch)
    answer = llm.run_pipeline({}, "keep listing", max_steps=2)
    assert answer == "done"
    assert model.calls[-1][1] is None  # final call asks for text, no tools


def test_conversation_context_is_injected(monkeypatch):
    state = session.new_state()
    state["entities"]["last_target"] = "Firefox"
    model = FakeModel([text_response("Closed.")])
    monkeypatch.setattr(llm, "ollama_chat", model)
    patch_dispatch(monkeypatch)
    llm.run_pipeline({}, "close it", state=state)
    messages = model.calls[0][0]
    assert any(m["role"] == "system" and "Firefox" in m["content"] for m in messages)


def test_ambiguous_result_sets_pending(monkeypatch):
    ambiguous = apps._ambiguous_result(
        "applications", "editor",
        [(250, {"name": "Kate", "id": "kate"}), (250, {"name": "VSCodium", "id": "vscodium"})],
    )
    model = FakeModel([tool_response("open_app", app="editor"), text_response("Which editor: Kate or VSCodium?")])
    monkeypatch.setattr(llm, "ollama_chat", model)
    patch_dispatch(monkeypatch, result=ambiguous)
    state = session.new_state()
    llm.run_pipeline({}, "open the editor", state=state)
    assert state["pending"]["options"] == ["Kate", "VSCodium"]


def test_tools_unsupported_falls_back_to_json(monkeypatch):
    calls = []
    sequence = {"n": 0}

    def fake(cfg, messages, tools_schema=None):
        sequence["n"] += 1
        if sequence["n"] == 1:
            assert tools_schema is not None
            raise llm.ToolsUnsupported("no tools")
        if sequence["n"] == 2:
            assert tools_schema is None
            return text_response('{"tool": "open_app", "arguments": {"app": "Firefox"}}')
        return text_response("done")

    monkeypatch.setattr(llm, "ollama_chat", fake)
    dispatched = patch_dispatch(monkeypatch, result="opened Firefox")
    assert llm.run_pipeline({}, "open firefox") == "done"
    assert dispatched == [("open_app", {"app": "Firefox"})]


def test_empty_model_output_returns_placeholder(monkeypatch):
    monkeypatch.setattr(llm, "ollama_chat", FakeModel([text_response("")]))
    patch_dispatch(monkeypatch)
    assert llm.run_pipeline({}, "hello") == "(no answer)"


def test_multiple_tool_calls_in_one_response(monkeypatch):
    model = FakeModel([
        {"message": {"content": "", "tool_calls": [
            {"function": {"name": "open_app", "arguments": {"app": "Firefox"}}},
            {"function": {"name": "open_app", "arguments": {"app": "kitty"}}},
        ]}},
        text_response("done"),
    ])
    monkeypatch.setattr(llm, "ollama_chat", model)
    calls = patch_dispatch(monkeypatch, result="opened")
    assert llm.run_pipeline({}, "open two apps") == "done"
    assert [c[1].get("app") for c in calls] == ["Firefox", "kitty"]


def test_prose_mentioning_a_tool_does_not_execute(monkeypatch):
    model = FakeModel([text_response('Just call {"name": "open_app", "arguments": {"app": "x"}} when ready.')])
    monkeypatch.setattr(llm, "ollama_chat", model)
    calls = patch_dispatch(monkeypatch)
    llm.run_pipeline({}, "how do I open an app?")
    assert calls == []


def test_leaked_tool_markup_returns_safe_fallback(monkeypatch):
    markup = '<tool_call>{"name": "not_a_tool", "arguments": {}}</tool_call>'
    model = FakeModel([text_response(markup), text_response(markup)])
    monkeypatch.setattr(llm, "ollama_chat", model)
    patch_dispatch(monkeypatch)
    answer = llm.run_pipeline({}, "do something")
    assert answer and "tool_call" not in answer and "{" not in answer


def test_exhausted_budget_with_only_envelope_falls_back(monkeypatch):
    envelope = '{"name": "open_app", "arguments": {"app": "x"}}'
    responses = [tool_response("list_apps", query="a"), tool_response("list_apps", query="b"),
                 text_response(envelope), text_response(envelope)]
    model = FakeModel(responses)
    monkeypatch.setattr(llm, "ollama_chat", model)
    patch_dispatch(monkeypatch, result="ok")
    answer = llm.run_pipeline({}, "go", max_steps=2)
    assert answer and "{" not in answer and "open_app" not in answer


def test_run_pipeline_reports_timings_without_content(monkeypatch):
    model = FakeModel([tool_response("open_app", app="Firefox"), text_response("Opened.")])
    monkeypatch.setattr(llm, "ollama_chat", model)
    patch_dispatch(monkeypatch, result="opened Firefox")
    metrics = {}
    llm.run_pipeline({}, "open firefox", metrics=metrics)
    assert {"steps", "llm_calls", "tool_calls", "llm_ms", "tool_ms", "total_ms"} <= set(metrics)
    # instrumentation must not carry user content
    assert all("firefox" not in str(value).lower() for value in metrics.values())
