"""Desktop context and precise target resolution. Fully mocked.

No real Hyprland/tmux session is touched: the low-level primitives are replaced.
These tests validate the deterministic side - parsing, identity, confirmation,
revalidation and refusal - and the plumbing that lets the LLM choose a target.
They do not (and cannot) prove the model understands a phrase.
"""

import json

import pytest

from hyprwhispr import desktop, llm, session, tools

FOCUSED = {"address": "0xabc", "title": "nvim app.py", "class": "kitty", "pid": 1234, "workspace": {"name": "1"}}
OTHER = {"address": "0xdef", "title": "Documentation - MDN", "class": "firefox", "pid": 2345, "workspace": {"name": "2"}}
THIRD = {"address": "0x123", "title": "GitHub", "class": "firefox", "pid": 2345, "workspace": {"name": "2"}}


def _fake_hypr(active=FOCUSED, clients=(FOCUSED, OTHER, THIRD)):
    def run(*args):
        if args == ("activewindow",):
            return active
        if args == ("clients",):
            return list(clients)
        return None
    return run


def _pane_line(pane_id, sess, win, pane, pactive, wactive, cmd, title, cwd, tty):
    return "\t".join([pane_id, sess, win, pane, pactive, wactive, cmd, title, cwd, tty])


def _fake_tmux(panes=None, clients=None):
    panes = panes if panes is not None else [
        _pane_line("%1", "work", "0", "0", "0", "0", "nvim", "app.py", "/home/u/proj", "/dev/pts/1"),
        _pane_line("%2", "work", "0", "1", "1", "1", "bash", "server", "/home/u/proj", "/dev/pts/2"),
    ]
    clients = clients if clients is not None else ["1300\t/dev/pts/2\twork"]

    def run(args):
        if args[:2] == ["list-panes", "-a"]:
            return True, "\n".join(panes)
        if args[:1] == ["list-clients"]:
            return True, "\n".join(clients)
        if args[:1] == ["kill-pane"]:
            return True, ""
        return False, ""
    return run


@pytest.fixture
def hypr(monkeypatch):
    monkeypatch.setattr(desktop, "available", lambda: True)
    monkeypatch.setattr(desktop, "_hyprctl_json", _fake_hypr())
    return monkeypatch


# --- window parsing -----------------------------------------------------------

def test_focused_window_normalizes(hypr):
    win = desktop.focused_window()
    assert win["address"] == "0xabc" and win["class"] == "kitty" and win["pid"] == 1234


def test_list_windows_marks_focused_and_filters(hypr):
    out = desktop.tool_list_windows({})
    assert "0xabc" in out and "[focused]" in out and "firefox" in out
    filtered = desktop.tool_list_windows({}, "firefox")
    assert "firefox" in filtered and "kitty" not in filtered


def test_list_windows_unavailable(monkeypatch):
    monkeypatch.setattr(desktop, "available", lambda: False)
    assert desktop.tool_list_windows({}).startswith("error:")


def test_context_line_reports_focused_or_unavailable(hypr):
    line = desktop.context_line({})
    assert "0xabc" in line and "kitty" in line and "nvim app.py" in line
    # opt-out and unavailable both yield no context (never invented)
    assert desktop.context_line({"desktop_context": False}) == ""
    monkey = hypr
    monkey.setattr(desktop, "available", lambda: False)
    assert desktop.context_line({}) == ""


# --- close_window -------------------------------------------------------------

def test_close_window_rejects_bad_address(hypr):
    out = desktop.tool_close_window({}, "not-an-address")
    assert out.startswith("error:") and "address" in out


def test_close_window_unknown_address(hypr):
    out = desktop.tool_close_window({}, "0xffff")
    assert out.startswith("error:") and "0xffff" in out


def test_close_window_denied_closes_nothing(hypr, monkeypatch):
    monkeypatch.setattr(desktop, "confirm", lambda *a, **k: False)
    dispatched = []
    monkeypatch.setattr(desktop, "_hyprctl_dispatch", lambda expr: dispatched.append(expr) or True)
    out = desktop.tool_close_window({}, "0xdef")
    assert "denied" in out and dispatched == []


def test_close_window_closes_exact_address(hypr, monkeypatch):
    monkeypatch.setattr(desktop, "confirm", lambda *a, **k: True)
    dispatched = []
    monkeypatch.setattr(desktop, "_hyprctl_dispatch", lambda expr: dispatched.append(expr) or True)
    out = desktop.tool_close_window({}, "0xdef")
    assert dispatched == ["closewindow address:0xdef"]
    assert "Documentation" in out


def test_close_window_aborts_when_target_disappears_after_confirm(hypr, monkeypatch):
    # the user confirms, but the window closes while they decide
    state = {"calls": 0}

    def flaky(address):
        state["calls"] += 1
        return desktop._normalize_window(OTHER) if state["calls"] == 1 else None

    monkeypatch.setattr(desktop, "window_by_address", flaky)
    monkeypatch.setattr(desktop, "confirm", lambda *a, **k: True)
    dispatched = []
    monkeypatch.setattr(desktop, "_hyprctl_dispatch", lambda expr: dispatched.append(expr) or True)
    out = desktop.tool_close_window({}, "0xdef")
    assert out.startswith("error:") and dispatched == []


# --- tmux ---------------------------------------------------------------------

def test_tmux_panes_parsing(monkeypatch):
    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", _fake_tmux())
    panes = desktop.tmux_panes()
    assert [p["pane_id"] for p in panes] == ["%1", "%2"]
    assert panes[1]["cwd"] == "/home/u/proj" and panes[1]["tty"] == "/dev/pts/2"


def test_list_tmux_panes_unavailable(monkeypatch):
    monkeypatch.setattr(desktop, "tmux_available", lambda: False)
    assert "not installed" in desktop.tool_list_tmux_panes({})


def test_list_tmux_panes_no_server(monkeypatch):
    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", lambda args: (False, ""))
    assert "no tmux server" in desktop.tool_list_tmux_panes({})


def test_list_tmux_panes_marks_focused(monkeypatch):
    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", _fake_tmux())
    monkeypatch.setattr(desktop, "focused_tmux_pane",
                        lambda: {"status": "ok", "pane": {"pane_id": "%2"}})
    out = desktop.tool_list_tmux_panes({})
    assert "%2" in out and "[focused]" in out


def test_close_tmux_pane_rejects_bad_id(monkeypatch):
    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    assert desktop.tool_close_tmux_pane({}, "2").startswith("error:")


def test_close_tmux_pane_unknown(monkeypatch):
    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", _fake_tmux())
    assert "no tmux pane" in desktop.tool_close_tmux_pane({}, "%9")


def test_close_tmux_pane_denied_kills_nothing(monkeypatch):
    seen = []

    def run(args):
        seen.append(args)
        return _fake_tmux()(args)

    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", run)
    monkeypatch.setattr(desktop, "confirm", lambda *a, **k: False)
    out = desktop.tool_close_tmux_pane({}, "%2")
    assert "denied" in out
    assert not any(a[:1] == ["kill-pane"] for a in seen)


def test_close_tmux_pane_kills_exact_pane(monkeypatch):
    seen = []

    def run(args):
        seen.append(args)
        return _fake_tmux()(args)

    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", run)
    monkeypatch.setattr(desktop, "confirm", lambda *a, **k: True)
    out = desktop.tool_close_tmux_pane({}, "%2")
    assert any(a[:3] == ["kill-pane", "-t", "%2"] for a in seen)
    assert "%2" in out


def test_close_tmux_pane_warns_on_last_pane(monkeypatch):
    single = [_pane_line("%1", "solo", "0", "0", "1", "1", "bash", "t", "/tmp", "/dev/pts/9")]
    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", _fake_tmux(panes=single))
    captured = {}
    monkeypatch.setattr(desktop, "confirm", lambda action, detail="": captured.update(d=detail) or False)
    desktop.tool_close_tmux_pane({}, "%1")
    assert "last pane" in captured["d"]


def test_close_tmux_pane_aborts_when_pane_disappears(monkeypatch):
    calls = {"n": 0}

    def run(args):
        if args[:2] == ["list-panes", "-a"]:
            calls["n"] += 1
            if calls["n"] == 1:
                return True, _pane_line("%2", "work", "0", "1", "1", "1", "bash", "s", "/tmp", "/dev/pts/2")
            return True, ""  # gone before the action
        return False, ""

    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", run)
    monkeypatch.setattr(desktop, "confirm", lambda *a, **k: True)
    out = desktop.tool_close_tmux_pane({}, "%2")
    assert out.startswith("error:")


def test_focused_tmux_pane_resolution(monkeypatch):
    monkeypatch.setattr(desktop, "available", lambda: True)
    monkeypatch.setattr(desktop, "_hyprctl_json", _fake_hypr())
    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", _fake_tmux())
    monkeypatch.setattr(desktop, "_process_table", lambda: {
        1234: {"ppid": 1, "comm": "kitty"},
        1300: {"ppid": 1234, "comm": "tmux"},
        1301: {"ppid": 1300, "comm": "bash"},
    })
    result = desktop.focused_tmux_pane()
    assert result["status"] == "ok" and result["pane"]["pane_id"] == "%2"


def test_focused_tmux_pane_ambiguous(monkeypatch):
    monkeypatch.setattr(desktop, "available", lambda: True)
    monkeypatch.setattr(desktop, "_hyprctl_json", _fake_hypr())
    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run",
                        _fake_tmux(clients=["1300\t/dev/pts/2\twork", "1302\t/dev/pts/3\twork"]))
    monkeypatch.setattr(desktop, "_process_table", lambda: {
        1234: {"ppid": 1, "comm": "kitty"},
        1300: {"ppid": 1234, "comm": "tmux"},
        1302: {"ppid": 1234, "comm": "tmux"},
    })
    assert desktop.focused_tmux_pane()["status"] == "ambiguous"


def test_focused_tmux_pane_not_found(monkeypatch):
    monkeypatch.setattr(desktop, "available", lambda: True)
    monkeypatch.setattr(desktop, "_hyprctl_json", _fake_hypr())
    monkeypatch.setattr(desktop, "tmux_available", lambda: True)
    monkeypatch.setattr(desktop, "tmux_run", _fake_tmux(clients=[]))
    monkeypatch.setattr(desktop, "_process_table", lambda: {1234: {"ppid": 1, "comm": "kitty"}})
    assert desktop.focused_tmux_pane()["status"] == "not_found"


# --- LLM plumbing: context in, chosen target out ------------------------------

def test_desktop_context_is_given_to_the_model(hypr):
    messages = llm._build_messages({}, "close this window", session.new_state())
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    assert "0xabc" in system  # the model is told the focused window's identity
    assert "list_windows" in system or "close_window" in llm.SYSTEM_PROMPT


def test_scripted_model_closes_the_focused_window(hypr, monkeypatch):
    address = desktop.focused_window()["address"]
    model = iter([
        {"message": {"content": "", "tool_calls": [
            {"function": {"name": "close_window", "arguments": {"address": address}}}]}},
        {"message": {"content": "Closed it."}},
    ])
    monkeypatch.setattr(llm, "ollama_chat", lambda *a, **k: next(model))
    seen = []
    monkeypatch.setattr(llm.tools, "dispatch_tool",
                        lambda cfg, name, args: seen.append((name, args)) or "closed window: x")
    answer = llm.run_pipeline({}, "get rid of this window", state=session.new_state())
    assert answer == "Closed it."
    assert seen == [("close_window", {"address": address})]


def test_scope_choice_routes_to_different_tools(hypr, monkeypatch):
    # "close every Firefox window" vs "close this window" -> different tools, both
    # dispatched with validated arguments. The choice is the model's; here it is
    # scripted so the pipeline plumbing is verified, not a phrase rule.
    def run(first):
        model = iter([{"message": {"content": "", "tool_calls": [{"function": first}]}},
                      {"message": {"content": "Done."}}])
        monkeypatch.setattr(llm, "ollama_chat", lambda *a, **k: next(model))
        seen = []
        monkeypatch.setattr(llm.tools, "dispatch_tool",
                            lambda cfg, name, args: seen.append((name, args)) or "ok")
        llm.run_pipeline({}, "x", state=session.new_state())
        return seen

    assert run({"name": "close_app", "arguments": {"app": "firefox"}}) == [("close_app", {"app": "firefox"})]
    assert run({"name": "close_window", "arguments": {"address": "0xdef"}}) == [("close_window", {"address": "0xdef"})]


def test_new_tools_are_registered():
    for name in ("list_windows", "close_window", "list_tmux_panes", "close_tmux_pane"):
        assert name in tools.TOOL_IMPL
        assert tools.TOOL_IMPL[name][0] is not None
    schema_names = {s["function"]["name"] for s in tools.TOOLS_SCHEMA}
    assert {"list_windows", "close_window", "list_tmux_panes", "close_tmux_pane"} <= schema_names
