# Tools

The model chooses tools from JSON schemas; it never emits shell text that
hyprwhispr executes. Argument types and lengths are validated in
`validation.py`. Every call is written to `logs/audit.jsonl` (tool name, status
and duration; arguments only when `log_tool_args` is enabled).

Every call also passes a **central authorization policy** (`policy.py`, Stage 6)
inside `dispatch_tool` *before* the tool body runs: unknown tools, missing or
oversized required arguments, and tools whose capability is disabled are refused,
and a refusal never falls through to another execution path. Tools are categorized
as read-only, reversible, or confirmed; see the inventory in `docs/security.md`.

## Safe tools (run automatically)

| Tool | Arguments | What it does |
|---|---|---|
| `open_app` | `app` | open a `.desktop` app or launch a Steam game by name |
| `list_apps` | `query?` | list installed desktop apps |
| `launch_steam_game` | `game` | launch a Steam game by name |
| `list_steam_games` | `query?` | list installed Steam games |
| `close_app` | `app` | close **all** windows of an app/game gracefully (confirmed) |
| `list_windows` | `query?` | list open windows with their Hyprland address (read-only) |
| `list_tmux_panes` | - | list tmux panes; marks the focused terminal's pane (read-only) |
| `get_selection` | - | selected/active context (AT-SPI name/text) and any verified selected file path |
| `read_document` | `path`, `reason?` | read a local file's text (opt-in; `document_read`; result is untrusted data) |
| `list_processes` | `query?` | list processes (id, name, ppid, cwd, redacted command) |
| `inspect_process` | `id` | details for one process; validates the id against fresh kernel data |
| `list_listening_ports` | `port?`, `proto?` | listening TCP/UDP sockets and the processes that own them |
| `inspect_project_services` | `project_path?` | processes whose working directory is inside the project |
| `capture_tmux_pane` | `pane_id`, `lines?` | bounded recent output from one tmux pane (untrusted data) |
| `list_services` | `project_path?` | registered services with status + evidence (read-only) |
| `inspect_service` | `service_id` | full definition + runtime status of one registered service |
| `service_logs` | `service_id`, `lines?` | bounded log tail from a service's configured log file (untrusted) |
| `launch_opencode` | `prompt?` | open OpenCode in a terminal (optionally pre-fill a prompt) |
| `web_search` | `query` | open a browser search (network; browser discovered, see below) |
| `save_note` | `text` | append to the local notes file |
| `list_notes` | `query?` | search local notes |
| `remember` | `key`, `value` | persist a preference |
| `recall` | `key?` | read a preference; with no key, list everything remembered |

## Confirmation-gated tools (always ask first)

| Tool | Arguments | What it does |
|---|---|---|
| `close_window` | `address`, `reason?` | close **one** window by its Hyprland address (confirmed + revalidated) |
| `close_tmux_pane` | `pane_id`, `reason?` | close **one** tmux pane by id (confirmed + revalidated) |
| `open_selected` | `reason?` | open the single verified selected file with the default handler (confirmed + revalidated) |
| `stop_process` | `id`, `reason?` | gracefully stop ONE process (SIGTERM) by exact id (confirmed + revalidated) |
| `start_service` | `service_id`, `reason?` | start a **registered** service (confirmed; argv, no shell) |
| `stop_service` | `service_id`, `reason?` | stop a registered service's managed process (confirmed; SIGTERM only) |
| `restart_service` | `service_id`, `reason?` | stop then start a registered service (confirmed; aborts on change) |
| `run_shell` | `command` | run one shell command (off by default — set `shell_control: true`) |
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

## Desktop targets (windows and tmux)

The model interprets the request; verified desktop context identifies the object.
`desktop.py` reads the focused window and the open windows from Hyprland
(`hyprctl`), and resolves the tmux pane shown in the focused terminal from the
window's process tree (not the `TMUX` environment, which may not match a
keybinding-launched assistant).

- Identity is the **Hyprland window address** for windows and the **tmux pane id**
  for panes. Titles/classes/commands help the model choose but are never the sole
  identity for a destructive action.
- `list_windows` / `list_tmux_panes` are read-only and need no confirmation.
- `close_window` / `close_tmux_pane` show the exact target, ask for confirmation,
  then **revalidate** the identity and abort if it changed or disappeared. The
  model can never invent an address or pane id, and a confirmed action authorizes
  only the target that was shown.
- Focus is not selection. Hyprland reveals the focused *window*, not a selected
  file, tab or document inside an application; for those the assistant says it
  cannot tell and asks the user.

## Selection context (Stage 3, optional)

The object selected/active *inside* an application (a highlighted file, an active
browser tab, a document in a viewer, selected text) is not the focused window and
cannot be inferred from a window title. Where the application exposes it through
**AT-SPI** (Linux accessibility), `selection.py` reads it and the model labels it
honestly:

- `context_type` is `selected_text`, `selected_item`, `tab` or `document`;
- `state` is `selected`, `active` or `displayed` - a *displayed* document is not a
  *selection*;
- `verified` is true only when AT-SPI reported it; otherwise the assistant says the
  selection is `unavailable`/`unsupported` and asks the user.

AT-SPI requires PyGObject/`pyatspi` and desktop accessibility enabled. The
standard-library venv cannot import `gi`, so the provider runs a **short-lived
helper** under an interpreter that can (auto-detected, or set `a11y_python`);
Flatpak/sandboxed apps may not appear on the bus at all. Set `"selection_context":
false` to disable it entirely.

A name reported by `get_selection` is not proof of a file path, so the assistant
does not invent one. Reading a file's *contents* (`read_document`) is a separate,
opt-in action (`document_read`, off by default); it needs an absolute path, is
size-bounded, shows the canonical path, and returns the text as **untrusted data,
never as instructions**.

### Verified file paths (Stage 3.1)

No desktop file manager exposes a D-Bus *query* for its current selection:
`org.freedesktop.FileManager1` is **call-in only** (`ShowItems`, `ShowFolders`, ...),
and `org.xfce.Thunar` / `org.kde.dolphin` do not publish the selection either. The
reliable, cross-file-manager, local interface is the **XDG primary selection**
carrying `text/uri-list`: when files are selected, the file manager offers their
`file://` URIs on the PRIMARY selection. `selection.py` reads that with
`wl-paste` (wl-clipboard) and:

- accepts only local `file://` URIs, parsed with a real URI parser
  (`urllib`), converting `%20` etc.; other schemes and remote hosts are rejected;
- canonicalizes the path (`os.path.realpath`) and requires it to exist;
- reports **exactly one** item as a verified path; if **several** are selected it
  says so and refuses to choose (never silently picks one);
- keeps this evidence separate from the AT-SPI name/text (labelled
  `source: primary-selection` vs `source: at-spi`).

`open_selected` opens the single verified selected file with the default handler
after confirmation and revalidation; `read_document` may read a verified path when
document reading is enabled. A selected item *name* alone never becomes a path.

## Processes and projects (Stage 4)

Read-only discovery is built from **verified local evidence**: `/proc/<pid>/stat`,
`/proc/<pid>/fd` (socket inodes), `/proc/net/{tcp,tcp6,udp,udp6}` listening
sockets, and the existing Hyprland/tmux context. No dependency is added and no
shell is used.

- **Identity is `(pid, start time)`**, not a PID. A bare PID can be reused, so
  every tool returns an `id` like `pid:4100:start:88123` and every action
  revalidates it against fresh kernel data — a reused PID is detected and
  refused. Command lines are **redacted** for secret-looking flags and
  length-bounded; environment variables are never read.
- `list_processes` / `inspect_process` (with ancestry and listening ports) /
  `list_listening_ports` / `inspect_project_services` / `capture_tmux_pane` are
  read-only. `inspect_project_services` resolves the project root conservatively
  (markers such as `.git`/`pyproject.toml`/`package.json`, walking up from the
  focused tmux pane or window's working directory) and lists processes whose
  **working directory is inside that root** — an inferred service name is never
  treated as verified identity.
- **Owning a port never authorizes stopping its owner.** `stop_process` takes the
  exact `id`, shows the process (pid, name, start, cwd, redacted command), asks for
  confirmation, revalidates the identity, sends **SIGTERM only**, waits a bounded
  5 s, and reports. It never escalates to `SIGKILL`, never uses `pkill -f`, never
  kills by name/port, and never terminates a whole tree on its own. If several
  candidates match, it asks which one. Disable it with `"process_control": false`.
- `capture_tmux_pane` returns bounded recent output (≤ 200 lines) labelled
  **untrusted data**; log text can never trigger a tool or change permissions.

**Not implemented (no verified mechanism):** starting or restarting services
(there is no service definition to trust — register the service instead, or, only
with `"shell_control": true`, use `run_shell` with an explicit, confirmed command),
recursive process-tree termination, and Docker/systemd/container orchestration.

## Registered services (Stage 5)

Full lifecycle management is available only for services the user has **registered**
by hand in `services.json` (schema in the configuration reference). The assistant
**reads** the registry and never writes to it, so it can never invent or execute a
launch command.

- **Ownership is exact and durable.** A managed `start_service` records the child's
  `(pid, start time)` identity in `state/services_runtime.json`. Later turns (each a
  fresh process) revalidate that identity against `/proc`; a reused PID is detected
  and treated as no managed runtime. Ownership is the **direct child only** — the
  assistant does not reconstruct or kill a process tree.
- **Status** is `STOPPED` (no valid managed runtime), `STARTING` (recent launch,
  readiness port not yet up), `RUNNING` (live managed process; if a `ready.port` is
  configured it must be listening *and owned by that process*, otherwise liveness
  only is the documented meaning), `UNHEALTHY` (readiness failing, or the port is
  held by another process), or `UNKNOWN`. A service is never reported healthy
  because a port is merely occupied.
- **Start** uses the validated argv with `cwd` and a **minimal environment**
  (`PATH`/`HOME`/…), never a shell. It refuses if the service is already running or
  the ready port is used by another process, confirms the exact command, records the
  identity, waits the startup timeout, and reports RUNNING/STARTING/failure honestly.
- **Stop** reuses the `stop_process` safeguards: confirm, revalidate the recorded
  identity, `SIGTERM` only, bounded wait, report. It never kills by name/port and
  never escalates to `SIGKILL`. A service started **outside** the manager has no
  managed runtime, so `stop_service` refuses rather than guess.
- **Restart** requires start+stop enabled, confirms once, **aborts if the definition
  changed** while deciding, and will **not start a replacement if the stop fails**.
- `service_logs` reads a bounded tail of the configured `log.path` and labels it
  untrusted data.

**Not supported:** managing unregistered services, discovering launch commands from a
project, `systemd`/Docker/container orchestration, and process-tree termination.

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
