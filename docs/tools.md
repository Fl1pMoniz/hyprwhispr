# Tools

The model chooses tools from JSON schemas; it never emits shell text that
hyprwhispr executes. Argument types and lengths are validated in
`validation.py`. Every call is written to `logs/audit.jsonl` (tool name, status
and duration; arguments only when `log_tool_args` is enabled).

## Safe tools (run automatically)

| Tool | Arguments | What it does |
|---|---|---|
| `open_app` | `app` | open a `.desktop` app or launch a Steam game by name |
| `list_apps` | `query?` | list installed desktop apps |
| `launch_steam_game` | `game` | launch a Steam game by name |
| `list_steam_games` | `query?` | list installed Steam games |
| `close_app` | `app` | close an app/game's windows gracefully |
| `launch_opencode` | `prompt?` | open OpenCode in a terminal (optionally pre-fill a prompt) |
| `web_search` | `query` | open a browser search (network; browser discovered, see below) |
| `save_note` | `text` | append to the local notes file |
| `list_notes` | `query?` | search local notes |
| `remember` | `key`, `value` | persist a preference |
| `recall` | `key?` | read a preference; with no key, list everything remembered |

## Confirmation-gated tools (always ask first)

| Tool | Arguments | What it does |
|---|---|---|
| `run_shell` | `command` | run one shell command |
| `install_package` | `package` | open a terminal to install a distro package |
| `delete_path` | `path` | move a file/folder to the trash (reversible) |

The confirmation dialog is `zenity` (or `rofi`). It **fails closed**: if no
dialog is available, or the user does not answer within 60 seconds, the action
is denied and recorded as denied.

## How the model chooses tools

Tool selection is model-driven (native Ollama function calling, with a strict
JSON fallback for servers without tool support). There is no keyword matching:
the assistant understands phrasing like "can you bring up my browser?" or "I'm
done playing, shut Steam down" because the model maps them to `open_app` /
`close_app`. Configured `apps` aliases (for example `browser`, `terminal`,
`editor`) are listed to the model so indirect references resolve.

A tool is only ever triggered by machine tool-call syntax — native calls, a
`<tool_call>` block, a fenced `json` block, or content that is itself a JSON
object naming a registered tool. Naming a tool in ordinary prose never runs it,
and any tool-call markup the model leaks into a reply is stripped before it
reaches the user (with one bounded retry if no user-facing text remains).

## Application and Steam discovery

`open_app` first checks the `apps` map in your config (handy aliases), then an
index of every installed `.desktop` file, then the Steam library. Names are
normalized (case, Unicode, punctuation) and filtered of filler words, so "my
web browser" and "Firefox!" both resolve. The Steam index is built from
`appmanifest_*.acf` files across all library folders plus Steam's own
shortcuts. Run `hyprwhispr refresh-apps` after installing new software; the
index also refreshes automatically after 24 hours. Use `hyprwhispr resolve
<query>` to see which candidates matched and their scores.

Launching uses `gtk-launch` (which honours flatpak apps and `Terminal=true`).
Closing focuses the matching window and asks the compositor to close it
(`hl.dsp.window.close()`), falling back to a graceful `SIGTERM` for windows that
ignore the request.

## Program discovery (never assume a program exists)

Before invoking an external program, hyprwhispr checks that it is actually
available (`discovery.py`):

* an explicit configured value is tried first (an absolute path is validated as
  an executable file; a bare name is looked up on `PATH`);
* otherwise a small, documented, ordered list of legitimate executable names is
  tried;
* `browser_bin` selects a preferred browser; without it the common browser names
  are tried, then a generic opener (`xdg-open`/`gio`);
* terminals fall back through `foot`, `alacritty`, `wezterm`, `konsole`,
  `gnome-terminal`, ... when the configured `terminal_bin` is missing;
* Steam and OpenCode are resolved the same way.

Discovery is a **capability check only**. Finding a program is separate from being
allowed to run it: every call still goes through the normal tool path, and the
confirmation gate is untouched. Lookups never scan the filesystem, launch nothing,
and never use a shell (URLs/paths are passed as separate argv elements). A short
lived, bounded cache avoids repeating the same lookup within one action. When
nothing is available the tool returns a clear `error:` explaining what to install
or configure; it never reports success because a program was merely found.

## Ambiguity and context

If a query matches several apps or games with no clear winner, `open_app` /
`close_app` do **not** guess: they return an `ambiguous:` result listing the
candidates. The assistant then asks the user a short question, and the choices
are remembered in the session so the next utterance ("KCalc") resolves.

References like "it", "that app" or "the previous one" are resolved from the
session context: the most recently referenced target is provided to the model
each turn. The context is bounded and expires (see `docs/configuration.md`), and
is separate from persistent notes/preferences.

## What can touch the network

Only `web_search`. It opens the URL in your browser; hyprwhispr itself never
fetches a page or sends your transcript anywhere. Speech recognition and answer
generation are always local. See `docs/security.md`.

## Adding a tool

1. Implement a function in the relevant module that returns a short string.
2. Add it to `TOOL_IMPL` and `TOOLS_SCHEMA` in `tools.py`.
3. If it changes state, call `permissions.confirm(...)` first.
4. Add a test under `tests/`.
