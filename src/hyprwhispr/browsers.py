"""Browser discovery and safe URL opening.

hyprwhispr never assumes a particular browser exists. When asked to open a URL or
the web browser, it:

1. honours an explicit ``browser_bin`` from the config, if set;
2. otherwise looks for a set of common Linux browser executables on ``PATH``;
3. falls back to a generic opener (``xdg-open`` / ``gio open``) if no browser
   executable is found;
4. reports clearly when nothing suitable is available.

Launching uses an argument vector (never a shell), so the URL is never
interpolated into a command line. Discovery is a capability check only; it does
not authorise anything, and opening a page is the same safe, non-destructive
action as before.
"""

from __future__ import annotations

import os
import subprocess

from . import discovery

#: Common Linux browser executables, most preferred first. Display names are used
#: only for messages. A browser installed under another name still resolves, and
#: a user can always set ``browser_bin`` explicitly.
BROWSERS = [
    ("firefox", "Firefox"),
    ("firefox-esr", "Firefox ESR"),
    ("librewolf", "LibreWolf"),
    ("waterfox", "Waterfox"),
    ("mozilla-firefox", "Firefox"),
    ("chromium", "Chromium"),
    ("chromium-browser", "Chromium"),
    ("brave-browser", "Brave"),
    ("brave", "Brave"),
    ("google-chrome-stable", "Google Chrome"),
    ("google-chrome", "Google Chrome"),
    ("microsoft-edge-stable", "Microsoft Edge"),
    ("microsoft-edge", "Microsoft Edge"),
    ("vivaldi-stable", "Vivaldi"),
    ("vivaldi", "Vivaldi"),
    ("opera", "Opera"),
    ("qutebrowser", "qutebrowser"),
    ("epiphany", "GNOME Web"),
    ("gnome-epiphany", "GNOME Web"),
    ("falkon", "Falkon"),
    ("midori", "Midori"),
    ("palemoon", "Pale Moon"),
]

BROWSER_NAMES = [name for name, _ in BROWSERS]
BROWSER_LABELS = dict(BROWSERS)

#: Generic openers used only if no real browser executable was found. They hand
#: the URL to the user's configured default, but are not browsers themselves.
GENERIC_OPENERS = ("xdg-open", "gio")


def select_browser(cfg: dict, *, use_cache: bool = True) -> discovery.Resolution:
    """Resolve the preferred/available browser without launching anything."""
    configured = str(cfg.get("browser_bin") or "").strip()
    return discovery.resolve_program(
        BROWSER_NAMES, configured, labels=BROWSER_LABELS,
        fallback_names=GENERIC_OPENERS, use_cache=use_cache,
    )


def _argv_for(program: str, url: str | None) -> list[str]:
    """Build the launch vector, handling the generic openers' syntax."""
    name = os.path.basename(program)
    if name == "gio":
        return [program, "open", url] if url else [program, "open", "."]
    if url is None:
        return [program]
    return [program, url]


def no_browser_message(resolution: discovery.Resolution) -> str:
    """A clear, actionable message for the 'no browser found' case."""
    if resolution.requested:
        return (f"error: no usable web browser found; the configured 'browser_bin' "
                f"({resolution.requested!r}) was not found. Install a browser or fix "
                f"\"browser_bin\" in your configuration.")
    return ("error: no web browser is installed or on PATH; install one (for example "
            "Firefox) or set \"browser_bin\" in your configuration.")


def launch_url(cfg: dict, url: str, *, browser: discovery.Resolution | None = None) -> str:
    """Open *url* in the resolved browser. Returns a short result string.

    Reuses *browser* when the caller already resolved it, so a single action does
    not repeat discovery. The URL is passed as a separate argv element - never
    interpolated into a shell command.
    """
    resolution = browser if browser is not None else select_browser(cfg)
    if not resolution.found:
        return no_browser_message(resolution)
    argv = _argv_for(resolution.program, url)
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return f"error: could not launch {resolution.label or resolution.program}: {exc}"
    return f"opened {url} in {resolution.label or resolution.program}"


def open_browser(cfg: dict, *, browser: discovery.Resolution | None = None) -> str:
    """Open the browser without navigating to a specific site."""
    resolution = browser if browser is not None else select_browser(cfg)
    if not resolution.found:
        return no_browser_message(resolution)
    url = None
    if os.path.basename(resolution.program) in GENERIC_OPENERS:
        url = cfg.get("search_url", "").split("?", 1)[0] or "https://duckduckgo.com"
    argv = _argv_for(resolution.program, url)
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return f"error: could not launch {resolution.label or resolution.program}: {exc}"
    return f"opened {resolution.label or resolution.program}"
