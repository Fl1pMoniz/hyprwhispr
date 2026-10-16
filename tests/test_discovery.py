"""Executable discovery: resolution, alternatives, fallbacks and caching."""

import stat

import pytest

from hyprwhispr import discovery


@pytest.fixture(autouse=True)
def _clear_cache():
    discovery.clear_cache()
    yield
    discovery.clear_cache()


def _exec(tmp_path, name):
    path = tmp_path / name
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_configured_absolute_path_is_used(tmp_path):
    exe = _exec(tmp_path, "mybrowser")
    res = discovery.resolve_program(["firefox"], configured=str(exe))
    assert res.found and res.program == str(exe) and res.source == "configured"
    assert res.used_alternative is False


def test_configured_absolute_path_missing_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", lambda name: "/usr/bin/firefox")
    res = discovery.resolve_program(["firefox"], configured=str(tmp_path / "gone"))
    assert res.found and res.source == "path" and res.used_alternative is True
    assert any(t.endswith("gone") for t in res.tried) and "firefox" in res.tried


def test_configured_name_on_path_is_configured(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", lambda name: "/usr/bin/" + name if name == "brave" else None)
    res = discovery.resolve_program(["firefox"], configured="brave")
    assert res.program == "/usr/bin/brave" and res.source == "configured"


def test_candidate_order_is_respected(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", lambda name: "/usr/bin/" + name if name == "chromium" else None)
    res = discovery.resolve_program(["firefox", "chromium"], labels={"chromium": "Chromium"})
    assert res.program == "/usr/bin/chromium" and res.label == "Chromium"


def test_no_program_returns_none(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", lambda name: None)
    res = discovery.resolve_program(["firefox", "chromium"])
    assert not res.found and res.source == "none" and res.program is None


def test_fallback_names_are_marked(monkeypatch):
    monkeypatch.setattr(discovery.shutil, "which", lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None)
    res = discovery.resolve_program(["firefox"], fallback_names=("xdg-open",))
    assert res.found and res.source == "fallback"


def test_is_executable_file(tmp_path):
    exe = _exec(tmp_path, "tool")
    plain = tmp_path / "plain"
    plain.write_text("x")
    assert discovery.is_executable_file(exe) is True
    assert discovery.is_executable_file(plain) is False
    assert discovery.is_executable_file(tmp_path / "missing") is False


def test_relative_path_with_separator_is_validated(tmp_path):
    # a path containing a separator is checked directly, never looked up on PATH
    res = discovery.resolve_program(["firefox"], configured="some/relative/path")
    assert not res.found


def test_cache_avoids_duplicate_lookups(monkeypatch):
    calls = {"n": 0}

    def counting_which(name):
        calls["n"] += 1
        return "/usr/bin/firefox" if name == "firefox" else None

    monkeypatch.setattr(discovery.shutil, "which", counting_which)
    first = discovery.resolve_program(["firefox", "chromium"])
    after_first = calls["n"]
    second = discovery.resolve_program(["firefox", "chromium"])
    assert first == second
    assert calls["n"] == after_first  # second call served from the cache
    discovery.clear_cache()
    discovery.resolve_program(["firefox", "chromium"])
    assert calls["n"] > after_first  # cleared cache re-checks


def test_cache_can_be_bypassed(monkeypatch):
    calls = {"n": 0}

    def counting_which(name):
        calls["n"] += 1
        return "/usr/bin/firefox"

    monkeypatch.setattr(discovery.shutil, "which", counting_which)
    discovery.resolve_program(["firefox"])
    discovery.resolve_program(["firefox"], use_cache=False)
    assert calls["n"] == 2
