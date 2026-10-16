"""Tests for scripts/install.sh.

All of these are safe on a developer machine: they use ``--check``/``--dry-run``,
an isolated HOME/data/config under ``tmp_path``, mocked commands, and never call
sudo, dnf, pipx, ollama or the network.
"""

import os
import shutil
import stat
import subprocess

import pytest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install.sh"

pytestmark = pytest.mark.skipif(
    not shutil.which("bash"), reason="installer tests need bash"
)

BASH = shutil.which("bash") or "bash"

FEDORA = 'ID=fedora\nID_LIKE="fedora"\nVARIANT_ID=workstation\n'
NOBARA = 'ID=nobara\nID_LIKE="rhel centos fedora"\nVARIANT_ID=kde\n'
SILVERBLUE = 'ID=fedora\nVARIANT_ID=silverblue\n'
BAZZITE = 'ID=bazzite\nID_LIKE=fedora\nVARIANT_ID=bazzite\n'
ALMA = 'ID=almalinux\nID_LIKE="rhel centos fedora"\n'
UBUNTU = 'ID=ubuntu\nID_LIKE=debian\n'


def _os_release(tmp_path, content):
    path = tmp_path / "os-release"
    path.write_text(content)
    return path


def _write_bin(bindir, name, body):
    bindir.mkdir(parents=True, exist_ok=True)
    f = bindir / name
    f.write_text("#!/usr/bin/env bash\n" + body)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)


def _base_env(tmp_path, os_release, path=None):
    home = tmp_path / "home"
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "HYPRWHISPR_OS_RELEASE": str(os_release),
        "HYPRWHISPR_DATA": str(tmp_path / "data"),
        "HYPRWHISPR_CONFIG": str(tmp_path / "config" / "config.json"),
        "HYPRWHISPR_RUNTIME": str(tmp_path / "run"),
        "NO_COLOR": "1",
    })
    if path is not None:
        env["PATH"] = path
    return env


def run_lib(tmp_path, expr, *, os_release=None, path=None, env_extra=None):
    os_release = os_release or _os_release(tmp_path, FEDORA)
    env = _base_env(tmp_path, os_release, path)
    env["HYPRWHISPR_INSTALL_LIB"] = "1"
    env.update(env_extra or {})
    return subprocess.run(
        [BASH, "-c", f'source "$1"; {expr}', "hyprwhispr-test", str(SCRIPT)],
        env=env, capture_output=True, text=True, timeout=30,
    )


def run_cli(tmp_path, args, *, os_release=None, path=None, stdin=subprocess.DEVNULL, env_extra=None, cwd=None):
    os_release = os_release or _os_release(tmp_path, FEDORA)
    env = _base_env(tmp_path, os_release, path)
    env.update(env_extra or {})
    return subprocess.run(
        [BASH, str(SCRIPT), *args],
        env=env, stdin=stdin, capture_output=True, text=True, timeout=30, cwd=cwd,
    )


# --- detection --------------------------------------------------------------

@pytest.mark.parametrize("content,expected", [
    (FEDORA, "fedora"),
    (NOBARA, "nobara"),
    (SILVERBLUE, "fedora-atomic"),
    (BAZZITE, "fedora-atomic"),
    (ALMA, "fedora-derived"),
    (UBUNTU, "unsupported"),
])
def test_detect_distro(tmp_path, content, expected):
    result = run_lib(tmp_path, "detect_distro", os_release=_os_release(tmp_path, content))
    assert result.stdout.strip() == expected, result.stdout + result.stderr


def test_unsupported_os_fails_without_changes(tmp_path):
    result = run_cli(tmp_path, ["--check"], os_release=_os_release(tmp_path, UBUNTU))
    assert result.returncode == 2
    assert "unsupported" in result.stdout.lower()
    assert not (tmp_path / "config").exists()


def test_atomic_variant_fails_clearly(tmp_path):
    result = run_cli(tmp_path, ["--check"], os_release=_os_release(tmp_path, SILVERBLUE))
    assert result.returncode == 2
    assert "atomic" in result.stdout.lower()


def test_help(tmp_path):
    result = run_cli(tmp_path, ["--help"])
    assert result.returncode == 0
    assert "Usage:" in result.stdout


# --- command / model detection ---------------------------------------------

def test_have_detects_present_and_missing_commands(tmp_path):
    bindir = tmp_path / "fakebin"
    _write_bin(bindir, "present-tool", ":")
    path = f"{bindir}:{os.environ['PATH']}"
    result = run_lib(tmp_path, "have present-tool; echo $?; have absent-tool; echo $?", path=path)
    assert result.stdout.split() == ["0", "1"]


def test_ollama_has_model(tmp_path):
    bindir = tmp_path / "fakebin"
    _write_bin(bindir, "ollama",
               'if [ "${1:-}" = list ]; then echo "NAME ID SIZE"; echo "qwen3:4b abc 2.5 GB"; fi\n')
    path = f"{bindir}:{os.environ['PATH']}"
    result = run_lib(tmp_path, "ollama_has_model qwen3:4b; echo $?; ollama_has_model qwen3:8b; echo $?", path=path)
    assert result.stdout.split() == ["0", "1"]


def test_ollama_api_up_reflects_curl(tmp_path):
    ok_bin = tmp_path / "ok"
    _write_bin(ok_bin, "curl", "exit 0\n")
    bad_bin = tmp_path / "bad"
    _write_bin(bad_bin, "curl", "exit 1\n")
    good = run_lib(tmp_path, "ollama_api_up; echo $?", path=f"{ok_bin}:{os.environ['PATH']}")
    bad = run_lib(tmp_path, "ollama_api_up; echo $?", path=f"{bad_bin}:{os.environ['PATH']}")
    assert good.stdout.strip() == "0"
    assert bad.stdout.strip() == "1"


def test_binding_present_detection(tmp_path):
    hypr = tmp_path / "hypr"
    hypr.mkdir()
    (hypr / "user_keybinds.lua").write_text('-- no binding here\n')
    env = {"HYPR_CONF_DIR": str(hypr)}
    assert run_lib(tmp_path, "binding_present; echo $?", env_extra=env).stdout.strip() == "1"
    (hypr / "user_keybinds.lua").write_text('exec_cmd("hyprwhispr record-start")\n')
    assert run_lib(tmp_path, "binding_present; echo $?", env_extra=env).stdout.strip() == "0"


# --- model checksum / config -----------------------------------------------

def test_verify_model_sha(tmp_path):
    junk = tmp_path / "ggml-small.bin"
    junk.write_bytes(b"not the real model")
    assert run_lib(tmp_path, f'verify_model_sha "{junk}"; echo $?').stdout.strip() == "1"
    unknown = tmp_path / "custom-model.bin"
    unknown.write_bytes(b"anything")
    assert run_lib(tmp_path, f'verify_model_sha "{unknown}"; echo $?').stdout.strip() == "0"


def test_config_valid(tmp_path):
    cfg = tmp_path / "config" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('{"model": "qwen3:4b"}')
    env = {"HYPRWHISPR_CONFIG": str(cfg)}
    assert run_lib(tmp_path, "config_valid; echo $?", env_extra=env).stdout.strip() == "0"
    cfg.write_text('{ not json')
    assert run_lib(tmp_path, "config_valid; echo $?", env_extra=env).stdout.strip() == "1"


# --- flows ------------------------------------------------------------------

def test_no_model_download_reports_skip(tmp_path):
    bindir = tmp_path / "fakebin"
    _write_bin(bindir, "ollama", 'if [ "${1:-}" = list ]; then echo "NAME ID"; fi\n')
    _write_bin(bindir, "curl", "exit 0\n")
    path = f"{bindir}:{os.environ['PATH']}"
    result = run_cli(tmp_path, ["--check", "--no-model-download"], path=path)
    assert "no-model-download" in result.stdout


def test_dry_run_makes_no_changes(tmp_path):
    bindir = tmp_path / "fakebin"
    sentinel = tmp_path / "SENTINEL"
    for name in ("sudo", "dnf", "dnf5", "pipx", "git", "cmake", "g++"):
        _write_bin(bindir, name, f'echo "called $0" >> "{sentinel}"\nexit 0\n')
    path = f"{bindir}:{os.environ['PATH']}"
    result = run_cli(tmp_path, ["--dry-run"], path=path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing was changed" in result.stdout
    assert not sentinel.exists(), "a mutating command ran during --dry-run"
    assert not (tmp_path / "config" / "config.json").exists()


def test_existing_config_is_preserved(tmp_path):
    cfg = tmp_path / "config" / "config.json"
    cfg.parent.mkdir(parents=True)
    original = '{"model": "custom:7b", "language": "en"}'
    cfg.write_text(original)
    result = run_cli(tmp_path, ["--dry-run"])
    assert result.returncode == 0
    assert cfg.read_text() == original


def test_non_interactive_run_declines_and_changes_nothing(tmp_path):
    bindir = tmp_path / "fakebin"
    sentinel = tmp_path / "SENTINEL"
    _write_bin(bindir, "sudo", f'echo ran >> "{sentinel}"\nexit 0\n')
    _write_bin(bindir, "dnf", f'echo ran >> "{sentinel}"\nexit 0\n')
    path = f"{bindir}:{os.environ['PATH']}"
    result = run_cli(tmp_path, ["--no-model-download"], path=path)  # no --yes, stdin not a tty
    assert result.returncode != 0
    assert "cancelled" in result.stdout.lower()
    assert not sentinel.exists()


def test_missing_sudo_is_reported(tmp_path):
    bindir = tmp_path / "fakebin"
    _write_bin(bindir, "dnf", "exit 0\n")   # package manager present
    # no sudo in this PATH, and no /usr/bin fallback for it
    result = run_lib(tmp_path, "ASSUME_YES=1; install_packages foo; echo rc=$?", path=str(bindir))
    assert "sudo not found" in result.stdout
    assert "rc=1" in result.stdout


def test_failed_package_install_is_reported(tmp_path):
    bindir = tmp_path / "fakebin"
    _write_bin(bindir, "dnf", "exit 0\n")
    _write_bin(bindir, "sudo", "exit 1\n")  # privilege escalation fails
    result = run_lib(tmp_path, "ASSUME_YES=1; install_packages foo; echo rc=$?", path=f"{bindir}:{os.environ['PATH']}")
    assert "rc=1" in result.stdout


def test_repeated_dry_run_is_idempotent(tmp_path):
    first = run_cli(tmp_path, ["--dry-run"])
    second = run_cli(tmp_path, ["--dry-run"])
    assert first.returncode == 0 and second.returncode == 0
    assert not (tmp_path / "config" / "config.json").exists()
    assert not (tmp_path / "data").exists()


def test_works_from_any_working_directory(tmp_path):
    # The installer must not depend on the caller's current directory.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = run_cli(tmp_path, ["--check"], cwd=str(elsewhere))
    assert result.returncode in (0, 1)  # not a usage/unsupported error
    assert "Detected system:" in result.stdout
    assert "No such file" not in result.stdout + result.stderr


def test_pipx_install_handles_path_without_ensurepath(tmp_path):
    """A pipx install into ~/.local/bin must be recognised even when that dir is
    not on PATH, and the installer must not edit shell files via ensurepath."""
    bindir = tmp_path / "fakebin"
    ensurepath_sentinel = tmp_path / "ensurepath-called"
    install_sentinel = tmp_path / "pipx-installed"
    _write_bin(bindir, "pipx", (
        'case "${1:-}" in\n'
        '  list) exit 0 ;;\n'  # no apps installed
        '  install)\n'
        '    mkdir -p "$HOME/.local/bin"\n'
        '    printf \'#!/usr/bin/env bash\\necho "hyprwhispr 1.1.0"\\n\' > "$HOME/.local/bin/hyprwhispr"\n'
        '    chmod +x "$HOME/.local/bin/hyprwhispr"\n'
        f'    touch "{install_sentinel}"; exit 0 ;;\n'
        '  ensurepath) '
        f'touch "{ensurepath_sentinel}"; exit 0 ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    ))
    _write_bin(bindir, "ollama", 'if [ "${1:-}" = list ]; then echo "NAME ID"; fi\n')
    _write_bin(bindir, "curl", "exit 0\n")
    # Pre-build a fake whisper-cli so the (real) whisper.cpp build is skipped.
    wcli = tmp_path / "data" / "whisper.cpp" / "build" / "bin" / "whisper-cli"
    wcli.parent.mkdir(parents=True)
    wcli.write_text("#!/usr/bin/env bash\nexit 0\n")
    wcli.chmod(wcli.stat().st_mode | stat.S_IEXEC)
    # PATH excludes the real ~/.local/bin so the fake pipx result must be found by path.
    path = f"{bindir}:/usr/bin:/bin"
    result = run_cli(tmp_path, ["--yes", "--no-model-download"], path=path, env_extra={
        "PATH": path,
    })
    assert install_sentinel.exists(), result.stdout + result.stderr
    assert not ensurepath_sentinel.exists(), "installer must not run pipx ensurepath"
    assert "hyprwhispr CLI installed" in result.stdout
    assert "not on PATH" in result.stdout
    assert not (tmp_path / "data" / "venv").exists(), "venv fallback should not run when pipx succeeded"


def test_failed_whisper_build_is_reported_as_failure(tmp_path):
    """A failed whisper.cpp build must make the installer exit nonzero, not
    silently succeed. The build script is driven with fake tools that fail."""
    bindir = tmp_path / "fakebin"
    _write_bin(bindir, "git", 'case "${1:-}" in clone) exit 1 ;; *) exit 0 ;; esac\n')
    for tool in ("cmake", "make", "c++"):
        _write_bin(bindir, tool, "exit 0\n")
    _write_bin(bindir, "pipx", (
        'case "${1:-}" in list) exit 0 ;;\n'
        '  install) mkdir -p "$HOME/.local/bin"; '
        'printf \'#!/usr/bin/env bash\\necho "hyprwhispr 1.1.0"\\n\' > "$HOME/.local/bin/hyprwhispr"; '
        'chmod +x "$HOME/.local/bin/hyprwhispr"; exit 0 ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    ))
    _write_bin(bindir, "ollama", 'if [ "${1:-}" = list ]; then echo "NAME ID"; fi\n')
    _write_bin(bindir, "curl", "exit 0\n")
    path = f"{bindir}:/usr/bin:/bin"
    result = run_cli(tmp_path, ["--yes", "--no-model-download"], path=path, env_extra={"PATH": path})
    assert result.returncode != 0
    assert "whisper" in result.stdout.lower()
    assert "failed" in result.stdout.lower() or "missing" in result.stdout.lower()


def test_check_reports_wake_word_option(tmp_path):
    result = run_cli(tmp_path, ["--check"])
    assert "wake-word" in result.stdout.lower() or "wake word" in result.stdout.lower()


def test_dry_run_with_wake_word_injects_nothing(tmp_path):
    bindir = tmp_path / "fakebin"
    sentinel = tmp_path / "INJECTED"
    _write_bin(bindir, "pipx", (
        'case "${1:-}" in\n'
        '  list) echo "hyprwhispr 1.1.0"; exit 0 ;;\n'
        f'  inject) touch "{sentinel}"; exit 0 ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    ))
    path = f"{bindir}:/usr/bin:/bin"
    result = run_cli(tmp_path, ["--dry-run", "--with-wake-word"], path=path, env_extra={"PATH": path})
    assert "wake-word engine" in result.stdout.lower()
    assert not sentinel.exists(), "dry-run must not install the wake-word engine"
