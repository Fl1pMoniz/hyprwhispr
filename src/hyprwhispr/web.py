"""Web search.

This is the only feature that can reach the network. It simply opens the user's
default browser on a search URL: the query leaves the machine, the assistant
never fetches or scrapes anything itself, and no page content is read back into
the model.

The browser is discovered rather than assumed (see :mod:`hyprwhispr.browsers`):
a configured ``browser_bin`` is used first, then a common installed browser, then
a generic opener - and a clear error is returned if none is available.
"""

from __future__ import annotations

import urllib.parse

from . import browsers
from .notify import notify
from .validation import args_ok


def tool_web_search(cfg: dict, query: str) -> str:
    if not args_ok(query, 500):
        return "error: invalid query"
    url = cfg["search_url"] + urllib.parse.quote_plus(query)
    resolution = browsers.select_browser(cfg)
    if not resolution.found:
        return browsers.no_browser_message(resolution)
    notify("Web search", f"Query sent to your browser (leaves this machine):\n{query}", timeout=5000)
    result = browsers.launch_url(cfg, url, browser=resolution)
    if result.startswith("error"):
        return result
    note = f" (preferred '{resolution.requested}' was not found)" if resolution.used_alternative else ""
    return f"opened a web search for '{query}' in {resolution.label or resolution.program}{note}"
