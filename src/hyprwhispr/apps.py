"""Application integration: launching, listing and closing desktop apps and
Steam games on Hyprland.

The launcher does not keep a hard-coded allow-list. Instead it builds an index
of every installed ``.desktop`` entry and every installed Steam game, then
resolves the user's spoken name against it. Launching is done with
``gtk-launch`` (which honours flatpak apps, ``Terminal=true`` and environment
wrappers); closing focuses the matching window and asks the compositor to close
it, falling back to a graceful ``SIGTERM``.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import shlex
import shutil
import signal
import subprocess
import time

from . import config
from .notify import log_event, notify
from .permissions import confirm
from .validation import args_ok, non_empty

_HOME = pathlib.Path.home()

DESKTOP_DIRS = [
    _HOME / ".local/share/applications",
    _HOME / ".local/share/flatpak/exports/share/applications",
    pathlib.Path("/usr/share/applications"),
    pathlib.Path("/usr/local/share/applications"),
    pathlib.Path("/var/lib/flatpak/exports/share/applications"),
]

STEAM_ROOTS = [
    _HOME / ".local/share/Steam",
    _HOME / ".steam/steam",
    _HOME / ".steam/root",
    _HOME / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
]

# Locale/field-code markers we must strip from a desktop Exec line are handled
# in _exec_argv().


# ---------------------------------------------------------------------------
# .desktop index
# ---------------------------------------------------------------------------


def _parse_desktop(path: pathlib.Path) -> dict | None:
    """Parse the [Desktop Entry] group of a .desktop file into a dict."""
    data: dict[str, str] = {}
    section = None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "Desktop Entry" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data.setdefault(key.strip(), value.strip())
    if data.get("Type", "Application") != "Application":
        return None
    if data.get("Hidden", "false").lower() == "true":
        return None
    if not data.get("Name"):
        return None
    return data


def build_app_index(cfg: dict) -> dict:
    """Scan all desktop directories and cache the result."""
    config.ensure_dirs()
    entries: dict[str, dict] = {}
    for directory in DESKTOP_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.desktop")):
            if path.name in entries:
                continue  # user entries (first dirs) win over system ones
            data = _parse_desktop(path)
            if not data:
                continue
            entries[path.name] = {
                "id": path.stem,
                "file": str(path),
                "name": data.get("Name", ""),
                "generic": data.get("GenericName", ""),
                "comment": data.get("Comment", ""),
                "keywords": [k for k in data.get("Keywords", "").split(";") if k],
                "exec": data.get("Exec", ""),
                "terminal": data.get("Terminal", "false").lower() == "true",
                "categories": data.get("Categories", ""),
                "nodisplay": data.get("NoDisplay", "false").lower() == "true",
            }
    index = {"built_at": config.now(), "apps": list(entries.values())}
    (config.CACHE_DIR / "apps.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    log_event({"event": "app_index_built", "count": len(entries)})
    return index


def load_app_index(cfg: dict, max_age_hours: int = 24) -> dict:
    path = config.CACHE_DIR / "apps.json"
    try:
        index = json.loads(path.read_text())
        built = datetime.datetime.fromisoformat(index.get("built_at", ""))
        age_hours = (datetime.datetime.now() - built).total_seconds() / 3600
        if age_hours <= max_age_hours and index.get("apps"):
            return index
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return build_app_index(cfg)


def _score_app(entry: dict, query: str, tokens: list[str]) -> int:
    name = entry["name"].lower()
    generic = entry.get("generic", "").lower()
    keywords = " ".join(entry.get("keywords", [])).lower()
    entry_id = entry["id"].lower()
    score = 0
    if name == query:
        score = 1000
    elif name.startswith(query):
        score = 600
    elif query in name:
        score = 400
    if entry_id == query:
        score = max(score, 900)
    elif entry_id.startswith(query):
        score = max(score, 550)
    elif query in entry_id:
        score = max(score, 130)
    if query in generic:
        score = max(score, 250)
    if query in keywords:
        score = max(score, 150)
    if tokens and all(t in f"{name} {generic} {keywords} {entry_id}" for t in tokens):
        score = max(score, 300)
    if score:
        score -= len(name) // 50  # prefer shorter names on near-ties
    return score


def resolve_app(index: dict, query: str) -> dict | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    tokens = [t for t in re.split(r"\W+", q) if t]
    best, best_score = None, 0
    for entry in index.get("apps", []):
        score = _score_app(entry, q, tokens)
        if score > best_score:
            best, best_score = entry, score
    return best if best_score > 0 else None


def _exec_argv(exec_line: str) -> list[str]:
    argv = [a for a in shlex.split(exec_line) if not re.fullmatch(r"%[fFuUdDnNickvm]", a)]
    return [a.replace("%%", "%") for a in argv]


def launch_desktop(cfg: dict, entry: dict) -> None:
    if shutil.which("gtk-launch"):
        proc = subprocess.Popen(
            ["gtk-launch", entry["id"]],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            returncode = proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            returncode = 0
        if returncode == 0:
            return
    argv = _exec_argv(entry.get("exec", ""))
    if not argv:
        raise RuntimeError("no Exec line and gtk-launch failed")
    if entry.get("terminal"):
        term = shutil.which(cfg["terminal_bin"]) or "kitty"
        argv = [term, "-e"] + argv
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# ---------------------------------------------------------------------------
# Steam game index
# ---------------------------------------------------------------------------


def build_steam_games(cfg: dict) -> dict:
    config.ensure_dirs()
    games: dict[str, str] = {}
    roots: set[pathlib.Path] = set()
    for base in STEAM_ROOTS:
        if (base / "steamapps").is_dir():
            roots.add(base)
    for root in list(roots):
        library_file = root / "steamapps" / "libraryfolders.vdf"
        if library_file.exists():
            for match in re.finditer(r'"path"\s+"([^"]+)"', library_file.read_text(errors="replace")):
                path = pathlib.Path(match.group(1))
                if (path / "steamapps").is_dir():
                    roots.add(path)
    for root in roots:
        for manifest in (root / "steamapps").glob("appmanifest_*.acf"):
            text = manifest.read_text(errors="replace")
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            if appid and name:
                games[appid.group(1)] = name.group(1)
    # Non-Steam shortcuts that Steam exported as .desktop files.
    for directory in (_HOME / ".local/share/applications", pathlib.Path("/usr/share/applications")):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.desktop"):
            data = _parse_desktop(path)
            if not data:
                continue
            match = re.search(r"steam://rungameid/(\d+)", data.get("Exec", ""))
            if match:
                games.setdefault(match.group(1), data.get("Name", path.stem))
    index = {
        "built_at": config.now(),
        "games": [{"appid": a, "name": n} for a, n in sorted(games.items(), key=lambda kv: kv[1].lower())],
    }
    (config.CACHE_DIR / "steam_games.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    log_event({"event": "steam_index_built", "count": len(games)})
    return index


def load_steam_games(cfg: dict, max_age_hours: int = 24) -> dict:
    path = config.CACHE_DIR / "steam_games.json"
    try:
        index = json.loads(path.read_text())
        built = datetime.datetime.fromisoformat(index.get("built_at", ""))
        age_hours = (datetime.datetime.now() - built).total_seconds() / 3600
        if age_hours <= max_age_hours and index.get("games"):
            return index
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return build_steam_games(cfg)


def resolve_game(index: dict, query: str) -> dict | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    best, best_score = None, 0
    for game in index.get("games", []):
        name = game["name"].lower()
        score = 1000 if name == q else 600 if name.startswith(q) else 400 if q in name else 0
        if score:
            score -= len(name) // 50
            if score > best_score:
                best, best_score = game, score
    return best if best_score > 0 else None


def launch_steam_game(cfg: dict, game: dict) -> None:
    steam = shutil.which("steam") or "steam"
    subprocess.Popen([steam, f"steam://rungameid/{game['appid']}"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# ---------------------------------------------------------------------------
# window helpers (Hyprland)
# ---------------------------------------------------------------------------


def _list_windows() -> list[dict]:
    try:
        out = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True, check=False).stdout
        return json.loads(out)
    except (OSError, json.JSONDecodeError):
        return []


def _name_tokens(*names: str) -> set[str]:
    tokens: set[str] = set()
    for name in names:
        if not name:
            continue
        name = name.lower()
        tokens.add(name)
        tokens.update(t for t in re.split(r"\W+", name) if len(t) >= 4)
    return tokens


def _hypr_dispatch(expression: str) -> None:
    subprocess.run(["hyprctl", "dispatch", expression], check=False,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _windows_matching(tokens: set[str]) -> list[dict]:
    hits = []
    for window in _list_windows():
        haystack = f"{window.get('class', '')} {window.get('title', '')}".lower()
        if any(token in haystack for token in tokens):
            hits.append(window)
    return hits


# ---------------------------------------------------------------------------
# tools exposed to the model
# ---------------------------------------------------------------------------


def tool_open_app(cfg: dict, app: str) -> str:
    if not non_empty(app, 120):
        return "error: no application name was provided; ask the user which app to open"
    key = app.strip().lower()
    configured = {k.lower(): v for k, v in cfg["apps"].items()}
    if key in configured:
        cmd = shlex.split(configured[key])
        if not shutil.which(cmd[0]):
            return f"error: launcher '{cmd[0]}' not found"
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return f"opened {app}"
    hit = resolve_app(load_app_index(cfg), app)
    if hit:
        launch_desktop(cfg, hit)
        return f"opened {hit['name']}"
    game = resolve_game(load_steam_games(cfg), app)
    if game:
        launch_steam_game(cfg, game)
        return f"launched the Steam game {game['name']}"
    return f"error: no installed app or Steam game matches '{app}'"


def tool_list_apps(cfg: dict, query: str = "") -> str:
    apps = [e for e in load_app_index(cfg).get("apps", []) if not e.get("nodisplay")]
    q = (query or "").strip().lower()
    names = sorted({e["name"] for e in apps})
    if q:
        matches = sorted({e["name"] for e in apps if q in e["name"].lower() or q in e.get("generic", "").lower()})
        if matches:
            return f"{len(matches)} apps match '{query}': " + ", ".join(matches[:40])
        return f"no app name contains '{query}'; some installed apps: " + ", ".join(names[:20])
    return f"{len(names)} apps installed: " + ", ".join(names[:40])


def tool_list_steam_games(cfg: dict, query: str = "") -> str:
    games = load_steam_games(cfg).get("games", [])
    q = (query or "").strip().lower()
    if q:
        matches = [g["name"] for g in games if q in g["name"].lower()]
        if matches:
            return f"{len(matches)} installed Steam games match '{query}': " + ", ".join(matches[:40])
        return f"no Steam game name contains '{query}'; installed games: " + ", ".join(g["name"] for g in games[:20])
    return f"{len(games)} Steam games installed: " + ", ".join(g["name"] for g in games[:40])


def tool_launch_steam_game(cfg: dict, game: str) -> str:
    if not args_ok(game, 200):
        return "error: invalid game name"
    hit = resolve_game(load_steam_games(cfg), game)
    if not hit:
        return f"error: no installed Steam game matches '{game}'"
    launch_steam_game(cfg, hit)
    return f"launching the Steam game {hit['name']}"


def tool_close_app(cfg: dict, app: str) -> str:
    """Close windows (and, if needed, terminate processes) for an app or game."""
    if not non_empty(app, 120):
        return "error: no application name was provided; ask the user which app to close"
    tokens = _name_tokens(app)
    app_entry = resolve_app(load_app_index(cfg), app)
    game_entry = resolve_game(load_steam_games(cfg), app)
    if app_entry:
        tokens |= _name_tokens(app_entry["name"], app_entry["id"])
    if game_entry:
        tokens |= _name_tokens(game_entry["name"])
        tokens.add(f"steam_app_{game_entry['appid']}")

    hits = _windows_matching(tokens)
    if hits:
        titles = sorted({(w.get("title") or w.get("class") or "") for w in hits})
        for window in hits:  # graceful close: focus the window, then close it
            _hypr_dispatch(f'hl.dsp.exec_raw("focuswindow address:{window["address"]}")')
            _hypr_dispatch("hl.dsp.window.close()")
        time.sleep(1.5)
        remaining = _windows_matching(tokens)
        for window in remaining:  # stubborn window: ask the process to quit
            pid = window.get("pid")
            if pid:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError, ValueError):
                    pass
        log_event({"event": "close_app", "target": app, "windows": len(hits), "terminated": len(remaining)})
        extra = f" ({len(remaining)} needed SIGTERM)" if remaining else ""
        return f"closed {len(hits)} window(s): {', '.join(titles)}{extra}"

    program = None
    if app_entry:
        argv = _exec_argv(app_entry.get("exec", ""))
        if argv:
            program = pathlib.Path(argv[0]).name
    if program:
        pids = subprocess.run(["pgrep", "-x", program], capture_output=True, text=True,
                              check=False).stdout.split()
        if pids and confirm(f"'{app}' has no window. Send SIGTERM to process '{program}' (pids {', '.join(pids)})?"):
            subprocess.run(["pkill", "-TERM", "-x", program], check=False)
            log_event({"event": "close_process", "target": app, "program": program})
            return f"sent SIGTERM to {program}"
    return f"error: nothing open matches '{app}'"


def tool_launch_opencode(cfg: dict, prompt: str = "") -> str:
    """Open the OpenCode coding agent in a terminal, optionally pre-filling a prompt."""
    terminal = shutil.which(cfg["terminal_bin"]) or cfg["terminal_bin"]
    opencode = cfg["opencode_bin"]
    if not pathlib.Path(opencode).exists():
        opencode = shutil.which("opencode") or "opencode"
    if prompt and args_ok(prompt, 4000):
        config.NOTES_DIR.mkdir(parents=True, exist_ok=True)
        with (config.NOTES_DIR / "opencode-prompts.md").open("a") as fh:
            fh.write(f"\n## {config.now()}\n{prompt}\n")
        if shutil.which("wl-copy"):
            subprocess.run(["wl-copy", prompt], check=False)
        notify("OpenCode", "Prepared prompt copied to your clipboard and saved to notes.", timeout=6000)
    subprocess.Popen([terminal, "-T", "OpenCode", "-e", opencode],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return "opened OpenCode in a new terminal window"
