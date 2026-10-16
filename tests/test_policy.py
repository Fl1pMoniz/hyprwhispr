"""Central tool-execution policy and the dispatch boundary (Stage 6)."""

import pytest

from hyprwhispr import policy, tools


def test_every_tool_is_categorized():
    assert set(tools.TOOL_IMPL) == set(policy.TOOL_KINDS)
    assert set(policy.CAPABILITY_GATES) <= set(policy.TOOL_KINDS)


def test_unknown_tool_is_rejected():
    ok, error = policy.authorize({}, "frobnicate", {}, [])
    assert not ok and "not authorized" in error


def test_required_argument_must_be_present():
    ok, error = policy.authorize({}, "open_app", {}, ["app"])
    assert not ok and "'app'" in error
    ok, error = policy.authorize({}, "open_app", {"app": "   "}, ["app"])
    assert not ok
    ok, error = policy.authorize({}, "open_app", {"app": "firefox"}, ["app"])
    assert ok and error is None


def test_oversized_argument_rejected():
    ok, error = policy.authorize({}, "open_app", {"app": "x" * 5000}, ["app"])
    assert not ok and "too long" in error


def test_non_object_arguments_rejected():
    assert policy.authorize({}, "open_app", "not-a-dict", ["app"]) == (
        False, "error: arguments for 'open_app' must be a JSON object")


@pytest.mark.parametrize("tool,gate", [
    ("run_shell", "shell_control"),
    ("stop_process", "process_control"),
    ("start_service", "service_lifecycle"),
    ("stop_service", "service_lifecycle"),
    ("restart_service", "service_lifecycle"),
    ("read_document", "document_read"),
])
def test_capability_gates(tool, gate):
    args = {"command": "echo hi", "id": "pid:1:start:1", "service_id": "x", "path": "/tmp/x"}
    ok, error = policy.authorize({}, tool, args, [])
    assert not ok and gate in error
    ok, error = policy.authorize({gate: True}, tool, args, [])
    assert ok and error is None


def test_read_only_tools_are_ungated():
    for tool in ("list_windows", "list_services", "get_selection", "list_processes"):
        assert policy.authorize({}, tool, {}, [])[0] is True


def test_run_shell_defaults_to_disabled():
    # run_shell is confirmed and gated off by default
    ok, _ = policy.authorize({}, "run_shell", {"command": "npm run dev"}, [])
    assert not ok


# --- dispatch boundary --------------------------------------------------------

def test_dispatch_rejects_unknown_tool():
    assert tools.dispatch_tool({}, "frobnicate", {}).startswith("error: unknown tool")


def test_dispatch_rejects_missing_required_argument():
    out = tools.dispatch_tool({}, "open_app", {})
    assert out.startswith("error:") and "'app'" in out


def test_dispatch_gate_prevents_execution(monkeypatch):
    # a denied run_shell must never reach the tool body / subprocess
    from hyprwhispr import system_actions
    monkeypatch.setattr(system_actions.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("executed")))
    out = tools.dispatch_tool({}, "run_shell", {"command": "npm run dev"})
    assert out.startswith("error:") and "shell execution is disabled" in out


def test_dispatch_allows_enabled_capability(monkeypatch):
    from hyprwhispr import system_actions
    monkeypatch.setattr(system_actions, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(system_actions.subprocess, "run",
                        lambda cmd, **k: __import__("types").SimpleNamespace(returncode=0, stdout="ok\n", stderr=""))
    out = tools.dispatch_tool({"shell_control": True}, "run_shell", {"command": "echo ok"})
    assert out.startswith("exit 0")


def test_dispatch_read_only_tool_runs():
    # recall is read-only and safe with the isolated config
    assert isinstance(tools.dispatch_tool({}, "recall", {}), str)


def test_policy_denial_does_not_fall_through(monkeypatch):
    # if the policy denies, the tool function must not be called at all
    called = []
    monkeypatch.setitem(tools.TOOL_IMPL, "delete_path",
                        (lambda cfg, path="": called.append(path) or "ran", ["path"]))
    out = tools.dispatch_tool({}, "delete_path", {})   # missing required path
    assert out.startswith("error:") and called == []
