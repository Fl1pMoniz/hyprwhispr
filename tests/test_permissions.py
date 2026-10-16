"""The confirmation gate must fail closed."""

from types import SimpleNamespace

from hyprwhispr import permissions


def test_confirm_denies_when_no_dialog_available(monkeypatch):
    monkeypatch.setattr(permissions.shutil, "which", lambda name: None)
    shown = []
    monkeypatch.setattr(permissions, "notify", lambda *a, **k: shown.append(a))
    assert permissions.confirm("Delete everything?") is False
    assert shown  # the user is told it was blocked


def test_confirm_returns_true_on_allow(monkeypatch):
    monkeypatch.setattr(permissions.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    monkeypatch.setattr(permissions.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    assert permissions.confirm("Install package?", "htop") is True


def test_confirm_returns_false_on_deny(monkeypatch):
    monkeypatch.setattr(permissions.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    monkeypatch.setattr(permissions.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    assert permissions.confirm("Delete file?", "/important") is False


def test_confirm_falls_back_to_rofi(monkeypatch):
    monkeypatch.setattr(permissions.shutil, "which", lambda name: None if name == "zenity" else "/usr/bin/rofi")
    monkeypatch.setattr(permissions.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="Allow\n"))
    assert permissions.confirm("Run?") is True
