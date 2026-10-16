# Tools

The model chooses tools from JSON schemas; it never emits shell text that
hyprwhispr executes. Argument types and lengths are validated in
`validation.py`. Every call is written to `logs/audit.jsonl`.

## Safe tools (run automatically)

| Tool | Arguments | What it does |
|---|---|---|
| `open_app` | `app` | open a `.desktop` app or launch a Steam game by name |
| `list_apps` | `query?` | list installed desktop apps |
| `launch_steam_game` | `game` | launch a Steam game by name |
| `list_steam_games` | `query?` | list installed Steam games |
| `close_app` | `app` | close an app/game's windows gracefully |
| `launch_opencode` | `prompt?` | open OpenCode in a terminal (optionally pre-fill a prompt) |
| `web_search` | `query` | open a browser search (network; see below) |
| `save_note` | `text` | append to the local notes file |
| `list_notes` | `query?` | search local notes |
| `remember` | `key`, `value` | persist a preference |
| `recall` | `key` | read a persisted preference |

## Confirmation-gated tools (always ask first)

| Tool | Arguments | What it does |
|---|---|---|
| `run_shell` | `command` | run one shell command |
| `install_package` | `package` | open a terminal to install a distro package |
| `delete_path` | `path` | move a file/folder to the trash (reversible) |

The confirmation dialog is `zenity` (or `rofi`). It **fails closed**: if no
dialog is available, or the user does not answer within 60 seconds, the action
is denied and recorded as denied.

## Application and Steam discovery

`open_app` first checks the `apps` map in your config (handy aliases), then an
index of every installed `.desktop` file, then the Steam library. The Steam index
is built from `appmanifest_*.acf` files across all library folders plus Steam's
own shortcuts. `list_apps` / `list_steam_games` show what is available. Run
`hyprwhispr refresh-apps` after installing new software; the index also refreshes
automatically after 24 hours.

Launching uses `gtk-launch` (which honours flatpak apps and `Terminal=true`).
Closing focuses the matching window and asks the compositor to close it
(`hl.dsp.window.close()`), falling back to a graceful `SIGTERM` for windows that
ignore the request.

## What can touch the network

Only `web_search`. It opens the URL in your browser; hyprwhispr itself never
fetches a page or sends your transcript anywhere. Speech recognition and answer
generation are always local. See `docs/security.md`.

## Adding a tool

1. Implement a function in the relevant module that returns a short string.
2. Add it to `TOOL_IMPL` and `TOOLS_SCHEMA` in `tools.py`.
3. If it changes state, call `permissions.confirm(...)` first.
4. Add a test under `tests/`.
