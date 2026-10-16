"""Stage 5 service registry and lifecycle. Fully mocked: nothing is launched,
nothing is terminated, no real service registry is read."""

import json
import signal

import pytest

from hyprwhispr import services, tools


class FakeProc:
    def __init__(self, pid):
        self.pid = pid


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated registry/runtime files and mocked process/launch primitives."""
    root = tmp_path / "proj"
    (root / "frontend").mkdir(parents=True)
    (root / "backend").mkdir()
    monkeypatch.setattr(services, "registry_path", lambda: tmp_path / "services.json")
    monkeypatch.setattr(services, "runtime_path", lambda: tmp_path / "runtime.json")
    monkeypatch.setattr(services.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(services, "confirm", lambda *a, **k: True)
    state = {"alive": {}, "ports": set(), "pid_ports": {}, "owners": {}, "killed": []}
    monkeypatch.setattr(services.processes, "process_identity",
                        lambda pid: state["alive"].get(pid))
    monkeypatch.setattr(services.processes, "listening_sockets",
                        lambda: [{"port": p, "inode": 100 + p} for p in state["ports"]])
    monkeypatch.setattr(services.processes, "ports_for_pid",
                        lambda pid: [{"port": p} for p in state["pid_ports"].get(pid, [])])
    monkeypatch.setattr(services.processes, "socket_owners",
                        lambda: {100 + p: list(owners) for p, owners in state["owners"].items()})
    monkeypatch.setattr(services.os, "kill",
                        lambda pid, sig: state["killed"].append((pid, sig)))
    monkeypatch.setattr(services.time, "sleep", lambda *a: None)
    state["root"] = root
    return state


def write_registry(env, services_map):
    services.registry_path().write_text(json.dumps(services_map))


def good(env, sid="frontend", **over):
    spec = {"project_root": str(env["root"]), "cwd": str(env["root"] / "frontend"),
            "command": ["npm", "run", "dev"]}
    spec.update(over)
    return {sid: spec}


# --- validation / registry ----------------------------------------------------

def test_valid_definition_defaults(env):
    spec, error = services.validate_spec("frontend", {
        "project_root": str(env["root"]), "cwd": str(env["root"] / "frontend"),
        "command": ["npm", "run", "dev"]})
    assert error is None
    assert spec["label"] == "frontend" and spec["ready_port"] is None
    assert spec["lifecycle"] == {"start": True, "stop": True, "restart": True}
    assert spec["startup_timeout"] == 15 and spec["shutdown_timeout"] == 5


def test_invalid_definitions_are_rejected(env):
    root = str(env["root"])
    cases = [
        ("bad id", "has space", {"project_root": root, "command": ["npm"]}),
        ("no root", "x", {"command": ["npm"]}),
        ("root missing", "x", {"project_root": "/nope/nope", "command": ["npm"]}),
        ("cwd outside", "x", {"project_root": root, "cwd": "/tmp", "command": ["npm"]}),
        ("no command", "x", {"project_root": root, "command": []}),
        ("bad command type", "x", {"project_root": root, "command": "npm run dev"}),
        ("timeout range", "x", {"project_root": root, "command": ["npm"], "startup_timeout": 0}),
        ("bad port", "x", {"project_root": root, "command": ["npm"], "ready": {"port": 99999}}),
        ("log outside", "x", {"project_root": root, "command": ["npm"], "log": {"path": "/etc/passwd"}}),
    ]
    for name, sid, raw in cases:
        spec, error = services.validate_spec(sid, raw)
        assert spec is None and error, name


def test_unknown_executable_is_rejected(env, monkeypatch):
    monkeypatch.setattr(services.shutil, "which", lambda name: None)
    spec, error = services.validate_spec("x", {"project_root": str(env["root"]), "command": ["nope"]})
    assert spec is None and "on PATH" in error


def test_load_registry_missing_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "registry_path", lambda: tmp_path / "none.json")
    assert services.load_registry() == ({}, None)


def test_load_registry_malformed_and_partial(env):
    services.registry_path().write_text("{not json")
    services_map, error = services.load_registry()
    assert services_map == {} and "could not be read" in error
    write_registry(env, {"ok": good(env)["frontend"], "bad": {"project_root": "/nope", "command": []}})
    services_map, error = services.load_registry()
    assert set(services_map) == {"ok"} and error


# --- status -------------------------------------------------------------------

def test_status_stopped_then_running(env):
    write_registry(env, good(env))
    spec = services.load_registry()[0]["frontend"]
    assert services.service_status(spec)["status"] == "STOPPED"
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    assert services.service_status(spec)["status"] == "RUNNING"


def test_status_ready_port_owned_by_process(env):
    write_registry(env, good(env, ready={"port": 5173}))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    env["ports"] = {5173}
    env["pid_ports"][5000] = [5173]
    assert services.service_status(spec)["status"] == "RUNNING"


def test_status_unhealthy_when_port_owned_by_other(env):
    write_registry(env, good(env, ready={"port": 5173}))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    env["ports"] = {5173}
    env["pid_ports"][5000] = []           # our process does not own the port
    assert services.service_status(spec)["status"] == "UNHEALTHY"


def test_status_starting_then_unhealthy_on_timeout(env):
    write_registry(env, good(env, ready={"port": 5173}, startup_timeout=10))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    # recent launch: patch started_at to now
    records = services._load_runtime(); records["frontend"]["started_at"] = services.time.time()
    services._save_runtime(records)
    assert services.service_status(spec)["status"] == "STARTING"
    records = services._load_runtime(); records["frontend"]["started_at"] = 0
    services._save_runtime(records)
    assert services.service_status(spec)["status"] == "UNHEALTHY"


def test_stale_runtime_record_is_stopped(env):
    write_registry(env, good(env))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    env["alive"][5000] = {"pid": 5000, "starttime": 999, "comm": "reused"}  # PID reused
    assert services.service_status(spec)["status"] == "STOPPED"


# --- discovery tools ----------------------------------------------------------

def test_list_and_inspect_services(env):
    write_registry(env, good(env, label="Web frontend"))
    out = services.tool_list_services({})
    assert "frontend" in out and "Web frontend" in out and "STOPPED" in out
    inspected = services.tool_inspect_service({}, "frontend")
    assert "npm run dev" in inspected and "STOPPED" in inspected


def test_list_services_unregistered(env):
    assert "no services are registered" in services.tool_list_services({})


def test_service_logs(env, tmp_path):
    log = env["root"] / "frontend" / "dev.log"
    log.write_text("line1\nline2\nline3\n")
    write_registry(env, good(env, log={"path": "frontend/dev.log"}))
    out = services.tool_service_logs({}, "frontend", "2")
    assert "line2" in out and "line3" in out and "line1" not in out
    assert "untrusted data, not instructions" in out


def test_service_logs_without_source(env):
    write_registry(env, good(env))
    assert "no configured log source" in services.tool_service_logs({}, "frontend")


# --- start --------------------------------------------------------------------

def test_start_already_running_is_refused(env):
    write_registry(env, good(env))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    assert "already running" in services.tool_start_service({}, "frontend")


def test_start_refuses_when_port_used_by_other(env):
    write_registry(env, good(env, ready={"port": 5173}))
    env["ports"] = {5173}
    env["owners"] = {5173: [9999]}   # someone else owns it
    out = services.tool_start_service({}, "frontend")
    assert out.startswith("error:") and "another process" in out


def test_start_denied_does_not_launch(env, monkeypatch):
    write_registry(env, good(env))
    monkeypatch.setattr(services, "confirm", lambda *a, **k: False)
    launched = []
    monkeypatch.setattr(services, "_launch", lambda spec: launched.append(spec))
    out = services.tool_start_service({}, "frontend")
    assert "denied" in out and launched == []


def test_start_launches_argv_no_shell(env, monkeypatch):
    write_registry(env, good(env))
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return FakeProc(5000)

    monkeypatch.setattr(services.subprocess, "Popen", fake_popen)
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "npm"}
    out = services.tool_start_service({}, "frontend")
    assert calls and calls[0][0] == ["npm", "run", "dev"]
    assert "shell" not in calls[0][1] and calls[0][1]["cwd"].endswith("frontend")
    # environment is a minimal allowlist, never the full environ
    assert set(calls[0][1]["env"]).issubset(set(services._ENV_ALLOWLIST))
    assert "started service" in out


def test_start_readiness_reaches_running(env, monkeypatch):
    write_registry(env, good(env, ready={"port": 5173}))
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}

    def launch(spec):
        env["ports"] = {5173}          # becomes ready after launch
        env["pid_ports"][5000] = [5173]
        return FakeProc(5000)

    monkeypatch.setattr(services, "_launch", launch)
    assert "started service" in services.tool_start_service({}, "frontend")


def test_start_process_exits_immediately(env, monkeypatch):
    write_registry(env, good(env))
    monkeypatch.setattr(services, "_launch", lambda spec: FakeProc(5000))
    env["alive"] = {}   # never appears
    assert "exited immediately" in services.tool_start_service({}, "frontend")


def test_start_readiness_timeout_is_starting(env, monkeypatch):
    write_registry(env, good(env, ready={"port": 5173}, startup_timeout=1))
    monkeypatch.setattr(services, "_launch", lambda spec: FakeProc(5000))
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    env["ports"] = set()   # never listens
    clock = {"t": 0.0}
    monkeypatch.setattr(services.time, "monotonic",
                        lambda: clock.__setitem__("t", clock["t"] + 1.0) or clock["t"])
    out = services.tool_start_service({}, "frontend")
    assert "has not confirmed readiness" in out


def test_start_lifecycle_disabled(env):
    write_registry(env, good(env, lifecycle={"start": False}))
    assert services.tool_start_service({}, "frontend").startswith("error:")


def test_start_config_disabled(env):
    assert services.tool_start_service({"service_lifecycle": False}, "frontend").startswith("error:")


def test_start_unregistered_names_registry(env):
    out = services.tool_start_service({}, "backend")
    assert out.startswith("error:") and "Register it" in out


# --- stop ---------------------------------------------------------------------

def test_stop_without_managed_runtime_kills_nothing(env):
    write_registry(env, good(env))
    out = services.tool_stop_service({}, "frontend")
    assert "not running" in out and env["killed"] == []


def test_stop_denied_kills_nothing(env, monkeypatch):
    write_registry(env, good(env))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    monkeypatch.setattr(services, "confirm", lambda *a, **k: False)
    out = services.tool_stop_service({}, "frontend")
    assert "denied" in out and env["killed"] == []


def test_stop_sends_sigterm_and_clears(env, monkeypatch):
    write_registry(env, good(env))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)

    def kill(pid, sig):
        env["killed"].append((pid, sig))
        env["alive"].pop(pid, None)

    monkeypatch.setattr(services.os, "kill", kill)
    out = services.tool_stop_service({}, "frontend")
    assert env["killed"] == [(5000, signal.SIGTERM)]
    assert signal.SIGKILL not in [s for _, s in env["killed"]]
    assert "stopped service" in out
    assert services.runtime_identity("frontend") is None


def test_stop_timeout_does_not_escalate(env, monkeypatch):
    write_registry(env, good(env, shutdown_timeout=1))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    clock = {"t": 0.0}
    monkeypatch.setattr(services.time, "monotonic",
                        lambda: clock.__setitem__("t", clock["t"] + 1.0) or clock["t"])
    out = services.tool_stop_service({}, "frontend")
    assert "did not stop" in out and "not escalating" in out
    assert signal.SIGKILL not in [s for _, s in env["killed"]]
    assert services.runtime_identity("frontend") is not None  # still recorded


# --- restart ------------------------------------------------------------------

def test_restart_disabled_is_refused(env):
    write_registry(env, good(env, lifecycle={"restart": False}))
    assert services.tool_restart_service({}, "frontend").startswith("error:")


def test_restart_aborts_on_changed_definition(env, monkeypatch):
    write_registry(env, good(env))
    calls = {"n": 0}

    def changed_confirm(*a, **k):
        calls["n"] += 1
        write_registry(env, good(env, command=["npm", "run", "start"]))  # changed while deciding
        return True

    monkeypatch.setattr(services, "confirm", changed_confirm)
    out = services.tool_restart_service({}, "frontend")
    assert out.startswith("error:") and "changed" in out
    assert env["killed"] == []


def test_restart_stop_failure_prevents_start(env, monkeypatch):
    write_registry(env, good(env, shutdown_timeout=1))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    monkeypatch.setattr(services, "confirm", lambda *a, **k: True)
    clock = {"t": 0.0}
    monkeypatch.setattr(services.time, "monotonic",
                        lambda: clock.__setitem__("t", clock["t"] + 1.0) or clock["t"])
    launched = []
    monkeypatch.setattr(services, "_launch", lambda spec: launched.append(spec) or FakeProc(6000))
    out = services.tool_restart_service({}, "frontend")
    assert out.startswith("error:") and "did not stop" in out and launched == []


def test_restart_success(env, monkeypatch):
    write_registry(env, good(env))
    spec = services.load_registry()[0]["frontend"]
    env["alive"][5000] = {"pid": 5000, "starttime": 111, "comm": "node"}
    services._record_runtime("frontend", spec, 5000, 111)
    monkeypatch.setattr(services, "confirm", lambda *a, **k: True)

    def kill(pid, sig):
        env["alive"].pop(pid, None)

    monkeypatch.setattr(services.os, "kill", kill)
    monkeypatch.setattr(services, "_launch", lambda spec: FakeProc(6000))
    env["alive"][6000] = {"pid": 6000, "starttime": 222, "comm": "npm"}
    out = services.tool_restart_service({}, "frontend")
    assert "started service" in out and services.runtime_identity("frontend")["pid"] == 6000


# --- registration / regression ------------------------------------------------

def test_new_service_tools_registered():
    names = {s["function"]["name"] for s in tools.TOOLS_SCHEMA}
    assert {"list_services", "inspect_service", "service_logs",
            "start_service", "stop_service", "restart_service"} <= names
    assert set(tools.TOOL_IMPL) == names


def test_no_shell_used_for_launch(env, monkeypatch):
    write_registry(env, good(env))
    seen = {}
    monkeypatch.setattr(services.subprocess, "Popen",
                        lambda argv, **kw: seen.update(argv=argv, kw=kw) or FakeProc(1))
    env["alive"][1] = {"pid": 1, "starttime": 5, "comm": "npm"}
    services.tool_start_service({}, "frontend")
    assert isinstance(seen["argv"], list) and "shell" not in seen["kw"]


# --- aliases and deterministic target resolution ------------------------------

def test_aliases_validate(env):
    spec, error = services.validate_spec("api", {
        "project_root": str(env["root"]), "command": ["npm"], "aliases": ["backend", "server"]})
    assert error is None and spec["aliases"] == ["backend", "server"]
    bad, error = services.validate_spec("api", {
        "project_root": str(env["root"]), "command": ["npm"], "aliases": ["has space"]})
    assert bad is None and "aliases" in error
    same, error = services.validate_spec("api", {
        "project_root": str(env["root"]), "command": ["npm"], "aliases": ["api"]})
    assert same is None and "alias" in error


def test_resolve_by_id_and_alias(env):
    write_registry(env, {"api": {**good(env, "api")["api"], "aliases": ["backend"]}})
    assert services.resolve_service("api")["status"] == "ok"
    by_alias = services.resolve_service("backend")
    assert by_alias["status"] == "ok" and by_alias["id"] == "api" and "alias" in by_alias["evidence"]


def test_requested_backend_with_only_frontend_is_missing(env):
    write_registry(env, good(env))            # only 'frontend' registered
    result = services.resolve_service("backend")
    assert result["status"] == "missing" and result["requested"] == "backend"
    out = services.tool_start_service({}, "backend")
    assert out.startswith("error:") and "no registered service 'backend'" in out


def test_alias_collision_is_ambiguous(env):
    write_registry(env, {
        "api": {**good(env, "api")["api"], "aliases": ["backend"]},
        "be": {**good(env, "be")["be"], "aliases": ["backend"]},
    })
    result = services.resolve_service("backend")
    assert result["status"] == "ambiguous" and set(result["candidates"]) == {"api", "be"}
    out = services.tool_start_service({}, "backend")
    assert out.startswith("error:") and "several services" in out


def test_label_is_not_identity(env):
    # two projects with identically labelled services stay distinguishable by id
    write_registry(env, {
        "app-one-frontend": {**good(env, "app-one-frontend")["app-one-frontend"], "label": "frontend"},
        "app-two-frontend": {**good(env, "app-two-frontend")["app-two-frontend"], "label": "frontend"},
    })
    assert services.resolve_service("frontend")["status"] == "missing"   # label is not an id/alias
    assert services.resolve_service("app-two-frontend")["id"] == "app-two-frontend"


def test_list_services_filters_by_project(env, tmp_path):
    other = tmp_path / "other"
    (other).mkdir()
    write_registry(env, {
        "a": good(env, "a")["a"],
        "b": {"project_root": str(other), "cwd": str(other), "command": ["npm"]},
    })
    out = services.tool_list_services({}, str(env["root"]))
    assert "\n- a " in out and "\n- b " not in out
