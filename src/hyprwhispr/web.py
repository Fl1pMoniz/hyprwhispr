"""Web search.

This is the only feature that can reach the network. It simply opens the user's
default browser on a search URL: the query leaves the machine, the assistant
never fetches or scrapes anything itself, and no page content is read back into
the model.
"""

from __future__ import annotations

import subprocess
import urllib.parse

from .notify import notify
from .validation import args_ok


def tool_web_search(cfg: dict, query: str) -> str:
    if not args_ok(query, 500):
        return "error: invalid query"
    url = cfg["search_url"] + urllib.parse.quote_plus(query)
    notify("Web search", f"Query sent to your browser (leaves this machine):\n{query}", timeout=5000)
    subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return f"opened a web search for '{query}' in the browser"
