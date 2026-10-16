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
import unicodedata

from . import browsers, config, discovery
from .notify import log_event, notify
from .permissions import confirm
from .validation import args_ok, non_empty

#: A match at or above this score (exact name, name prefix, exact desktop id) is
#: trusted without asking; weaker matches must be unambiguous or we ask.
CONFIDENT_SCORE = 600

#: Common terminal emulators, most preferred first. Used when a desktop entry
#: needs a terminal, when launching OpenCode, or when closing a terminal app.
TERMINALS = [
    "kitty", "foot", "alacritty", "wezterm", "konsole",
    "gnome-terminal", "xfce4-terminal", "tilix", "xterm",
]

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
    name = normalize(entry.get("name"))
    generic = normalize(entry.get("generic"))
    keywords = normalize(" ".join(entry.get("keywords", [])))
    entry_id = normalize(entry.get("id"))
    haystack = f"{name} {generic} {keywords} {entry_id}"
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
    if tokens and all(t in haystack for t in tokens):
        score = max(score, 300)
    if score:
        score -= len(name) // 50  # prefer shorter names on near-ties
    return score


def resolve_app_candidates(index: dict, query: str, limit: int = 6) -> list[tuple[int, dict]]:
    """Return the best ``(score, entry)`` matches, highest first."""
    cleaned, tokens = _clean_query(query)
    if not cleaned:
        return []
    scored = [(_score_app(entry, cleaned, tokens), entry) for entry in index.get("apps", [])]
    scored = [(score, entry) for score, entry in scored if score > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:limit]


def resolve_app(index: dict, query: str) -> dict | None:
    candidates = resolve_app_candidates(index, query, limit=1)
    return candidates[0][1] if candidates else None


def _is_confident(top_score: int, candidates: list[tuple[int, dict]], cfg: dict) -> bool:
    """True when the top match is safe to act on without asking."""
    if top_score >= CONFIDENT_SCORE:
        return True
    if len(candidates) == 1:
        return True
    margin = int(cfg.get("app_ambiguity_margin", 150))
    return top_score >= 400 and (top_score - candidates[1][0]) >= margin


def format_candidates(candidates: list[tuple[int, dict]]) -> str:
    return ", ".join(entry.get("name", "?") for _, entry in candidates)


def _exec_argv(exec_line: str) -> list[str]:
    argv = [a for a in shlex.split(exec_line) if not re.fullmatch(r"%[fFuUdDnNickvm]", a)]
    return [a.replace("%%", "%") for a in argv]


def normalize(text: str | None) -> str:
    """Casefold, NFKC-normalise and reduce punctuation/spacing so that
    "Firefox!", "FIREFOX" and "firefox" compare equally."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"[_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


#: Words that carry no target information; dropped before matching so that
#: "my browser", "the editor" and "please open Firefox" resolve cleanly.
STOPWORDS = {
    "my", "the", "a", "an", "this", "that", "these", "those", "please",
    "app", "application", "program", "game", "to", "for", "me", "you", "up",
    "on", "of", "open", "launch", "start", "close", "quit", "play", "bring",
    "get", "run", "can", "could", "would",
}


def _clean_query(query: str) -> tuple[str, list[str]]:
    normalized = normalize(query)
    tokens = [t for t in normalized.split() if t not in STOPWORDS and len(t) >= 2]
    return (" ".join(tokens) if tokens else normalized), tokens


def _match_configured(configured: dict[str, str], query: str) -> tuple[str | None, str | None]:
    """Return ``(key, command)`` of a configured launcher matching the query."""
    normalized = normalize(query)
    if normalized in configured:
        return normalized, configured[normalized]
    query_tokens = set(normalized.split())
    for key, command in configured.items():
        if key and (key in query_tokens or any(tok in key.split() for tok in query_tokens)):
            return key, command
    return None, None


def _program_available(program: str) -> bool:
    """True when *program* is an executable path or resolves on ``PATH``."""
    program = (program or "").strip()
    if not program:
        return False
    if os.sep in program:
        return discovery.is_executable_file(program)
    return shutil.which(program) is not None


def resolve_terminal(cfg: dict) -> discovery.Resolution:
    """Find a usable terminal emulator (configured first, then common ones)."""
    configured = str(cfg.get("terminal_bin") or "").strip()
    return discovery.resolve_program(TERMINALS, configured, use_cache=False)


def _is_browser_alias(key: str | None) -> bool:
    return bool(key) and "browser" in key.split()


def _url_from_argv(argv: list[str]) -> str | None:
    for token in argv:
        if isinstance(token, str) and token.startswith(("http://", "https://")):
            return token
    return None


def _steam_program(cfg: dict) -> str | None:
    return shutil.which("steam")


def launch_desktop(cfg: dict, entry: dict) -> str:
    """Launch a desktop entry, returning its display name on success.

    Raises ``RuntimeError`` with an actionable message when the launcher cannot
    be started (missing gtk-launch, no Exec line, or a missing absolute
    executable), so the caller never reports a launch that did not happen.
    """
    if shutil.which("gtk-launch"):
        try:
            proc = subprocess.Popen(
                ["gtk-launch", entry["id"]],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise RuntimeError(f"gtk-launch could not start: {exc}") from exc
        try:
            returncode = proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            returncode = 0
        if returncode == 0:
            return entry.get("name", entry["id"])
    argv = _exec_argv(entry.get("exec", ""))
    if not argv:
        raise RuntimeError("no Exec line and gtk-launch failed")
    first = argv[0]
    if os.sep in first and not discovery.is_executable_file(first):
        raise RuntimeError(f"the program in the desktop entry is missing: {first}")
    if entry.get("terminal"):
        terminal = resolve_terminal(cfg)
        if not terminal.found:
            raise RuntimeError("no terminal emulator is installed")
        argv = [terminal.program, "-e"] + argv
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise RuntimeError(f"could not launch {first}: {exc}") from exc
    return entry.get("name", entry["id"])


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


def _score_game(game: dict, query: str) -> int:
    name = normalize(game.get("name"))
    if not name:
        return 0
    if name == query:
        score = 1000
    elif name.startswith(query):
        score = 600
    elif query in name:
        score = 400
    else:
        score = 0
    if score:
        score -= len(name) // 50
    return score


def resolve_game_candidates(index: dict, query: str, limit: int = 6) -> list[tuple[int, dict]]:
    cleaned, _ = _clean_query(query)
    if not cleaned:
        return []
    scored = [(_score_game(game, cleaned), game) for game in index.get("games", [])]
    scored = [(score, game) for score, game in scored if score > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:limit]


def resolve_game(index: dict, query: str) -> dict | None:
    candidates = resolve_game_candidates(index, query, limit=1)
    return candidates[0][1] if candidates else None


def launch_steam_game(cfg: dict, game: dict) -> None:
    steam = _steam_program(cfg)
    if not steam:
        raise RuntimeError("Steam is not installed or not on PATH")
    try:
        subprocess.Popen([steam, f"steam://rungameid/{game['appid']}"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise RuntimeError(f"could not start Steam: {exc}") from exc


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
        normalized = normalize(name)
        if not normalized:
            continue
        tokens.add(normalized)
        tokens.update(t for t in normalized.split() if len(t) >= 4)
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


AMBIGUOUS_PREFIX = "ambiguous: "


def parse_ambiguous(result: str) -> list[str]:
    """Extract the candidate names from an ``ambiguous:`` tool result."""
    if not result.startswith(AMBIGUOUS_PREFIX):
        return []
    match = re.search(r"\[([^\]]*)\]", result)
    if not match:
        return []
    return [name.strip() for name in match.group(1).split(",") if name.strip()]


def _ambiguous_result(kind: str, query: str, candidates: list[tuple[int, dict]]) -> str:
    names = format_candidates(candidates)
    return (f"{AMBIGUOUS_PREFIX}[{names}] several {kind} match '{query}'. "
            "Ask the user which one they mean before acting.")


def tool_open_app(cfg: dict, app: str) -> str:
    if not non_empty(app, 120):
        return "error: no application name was provided; ask the user which app to open"
    configured = {normalize(k): v for k, v in cfg["apps"].items()}
    key, command = _match_configured(configured, app)
    if command:
        cmd = shlex.split(command)
        program = cmd[0] if cmd else ""
        if _program_available(program):
            try:
                subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as exc:
                return f"error: could not launch '{program}': {exc}"
            return f"opened {app}"
        # The configured launcher is missing. For a browser alias, fall back to a
        # discovered browser; otherwise report the problem explicitly.
        if _is_browser_alias(key):
            resolution = browsers.select_browser(cfg)
            if resolution.found:
                url = _url_from_argv(cmd) or cfg.get("search_url", "").split("?", 1)[0] or "about:blank"
                result = browsers.launch_url(cfg, url, browser=resolution)
                if not result.startswith("error"):
                    return f"opened {app} with {resolution.label or resolution.program}"
            return browsers.no_browser_message(resolution)
        return f"error: configured launcher '{program}' for '{key}' was not found on PATH"

    app_candidates = resolve_app_candidates(load_app_index(cfg), app)
    game_candidates = resolve_game_candidates(load_steam_games(cfg), app)
    best_app = app_candidates[0] if app_candidates else None
    best_game = game_candidates[0] if game_candidates else None

    if best_app and (best_game is None or best_app[0] >= best_game[0]):
        if _is_confident(best_app[0], app_candidates, cfg):
            try:
                launch_desktop(cfg, best_app[1])
            except RuntimeError as exc:
                return f"error: {exc}"
            return f"opened {best_app[1]['name']}"
        return _ambiguous_result("applications", app, app_candidates)
    if best_game:
        if _is_confident(best_game[0], game_candidates, cfg):
            if not _steam_program(cfg):
                return "error: Steam is not installed or not on PATH"
            try:
                launch_steam_game(cfg, best_game[1])
            except RuntimeError as exc:
                return f"error: {exc}"
            return f"launched the Steam game {best_game[1]['name']}"
        return _ambiguous_result("Steam games", app, game_candidates)
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
    if not non_empty(game, 200):
        return "error: invalid game name"
    candidates = resolve_game_candidates(load_steam_games(cfg), game)
    if not candidates:
        return f"error: no installed Steam game matches '{game}'"
    if not _is_confident(candidates[0][0], candidates, cfg):
        return _ambiguous_result("Steam games", game, candidates)
    if not _steam_program(cfg):
        return "error: Steam is not installed or not on PATH"
    try:
        launch_steam_game(cfg, candidates[0][1])
    except RuntimeError as exc:
        return f"error: {exc}"
    return f"launching the Steam game {candidates[0][1]['name']}"


def _resolve_target(cfg: dict, name: str) -> tuple[dict | None, dict | None, str | None]:
    """Resolve a name to at most one app and one game, or explain the ambiguity.

    Returns ``(app_entry, game_entry, error)``. When ``error`` is set the caller
    must surface it and take no action.
    """
    app_candidates = resolve_app_candidates(load_app_index(cfg), name)
    game_candidates = resolve_game_candidates(load_steam_games(cfg), name)
    best_app = app_candidates[0] if app_candidates else None
    best_game = game_candidates[0] if game_candidates else None

    if best_app and (best_game is None or best_app[0] >= best_game[0]):
        if _is_confident(best_app[0], app_candidates, cfg):
            return best_app[1], None, None
        return None, None, _ambiguous_result("applications", name, app_candidates)
    if best_game:
        if _is_confident(best_game[0], game_candidates, cfg):
            return None, best_game[1], None
        return None, None, _ambiguous_result("Steam games", name, game_candidates)
    return None, None, None


def tool_close_app(cfg: dict, app: str) -> str:
    """Close windows (and, if needed, terminate processes) for an app or game."""
    if not non_empty(app, 120):
        return "error: no application name was provided; ask the user which app to close"
    app_entry, game_entry, ambiguity = _resolve_target(cfg, app)
    if ambiguity:
        return ambiguity

    tokens = _name_tokens(app)
    if app_entry:
        tokens |= _name_tokens(app_entry["name"], app_entry["id"])
    if game_entry:
        tokens |= _name_tokens(game_entry["name"])
        tokens.add(f"steam_app_{game_entry['appid']}")

    hits = _windows_matching(tokens)
    if hits:
        titles = sorted({(w.get("title") or w.get("class") or "") for w in hits})
        detail = "\n".join(titles[:8]) + (f"\n(+{len(titles) - 8} more)" if len(titles) > 8 else "")
        if not confirm(f"Close {len(hits)} window(s) for '{app}'?", detail):
            log_event({"event": "tool_denied", "tool": "close_app", "target": app})
            return "user denied closing the windows"
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
    if program and shutil.which("pgrep") and shutil.which("pkill"):
        pids = subprocess.run(["pgrep", "-x", program], capture_output=True, text=True,
                              check=False).stdout.split()
        if pids and confirm(f"'{app}' has no window. Send SIGTERM to process '{program}' (pids {', '.join(pids)})?"):
            subprocess.run(["pkill", "-TERM", "-x", program], check=False)
            log_event({"event": "close_process", "target": app, "program": program})
            return f"sent SIGTERM to {program}"
    return f"error: nothing open matches '{app}'"


def tool_resolve(cfg: dict, query: str) -> str:
    """Debug helper: show what the resolver finds for a query (no action taken)."""
    if not non_empty(query, 200):
        return "error: no query provided"
    app_candidates = resolve_app_candidates(load_app_index(cfg), query, limit=8)
    game_candidates = resolve_game_candidates(load_steam_games(cfg), query, limit=8)
    lines = [f"resolve '{query}':"]
    if not app_candidates and not game_candidates:
        lines.append("  no matches")
    for score, entry in app_candidates:
        lines.append(f"  app  [{score}] {entry['name']}  (id: {entry['id']})")
    for score, game in game_candidates:
        lines.append(f"  game [{score}] {game['name']}  (appid: {game['appid']})")
    return "\n".join(lines)


def tool_launch_opencode(cfg: dict, prompt: str = "") -> str:
    """Open the OpenCode coding agent in a terminal, optionally pre-filling a prompt."""
    terminal = resolve_terminal(cfg)
    if not terminal.found:
        return ("error: no terminal emulator is installed (tried "
                + ", ".join(TERMINALS) + "); set \"terminal_bin\" in your configuration")
    opencode = discovery.resolve_program(["opencode"], str(cfg.get("opencode_bin") or "").strip())
    if not opencode.found:
        return ("error: OpenCode was not found on PATH; install it or set "
                "\"opencode_bin\" in your configuration")
    if prompt and args_ok(prompt, 4000):
        config.NOTES_DIR.mkdir(parents=True, exist_ok=True)
        with (config.NOTES_DIR / "opencode-prompts.md").open("a") as fh:
            fh.write(f"\n## {config.now()}\n{prompt}\n")
        if shutil.which("wl-copy"):
            subprocess.run(["wl-copy", prompt], check=False)
        notify("OpenCode", "Prepared prompt copied to your clipboard and saved to notes.", timeout=6000)
    try:
        subprocess.Popen([terminal.program, "-T", "OpenCode", "-e", opencode.program],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return f"error: could not open OpenCode: {exc}"
    return "opened OpenCode in a new terminal window"
