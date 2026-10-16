# Security model

hyprwhispr runs on your desktop with your user's privileges. It is designed to be
predictable and local-first.

## Trust boundary

- **The transcript is untrusted input.** A mis-recognised phrase can ask for
  anything, exactly like typing it. The defence is not filtering words; it is the
  tool layer: the model can only request tools that exist, with typed arguments.
- **Tool arguments are validated** for type and length (`validation.py`). The
  model never supplies a shell string that runs directly: `install_package`
  builds a fixed `sudo dnf install <validated-name>` vector, `delete_path`
  resolves and trashes a path, and `run_shell` is the only tool that runs an
  arbitrary command — it always asks first, and it is **disabled unless
  `shell_control` is enabled**.
- **High-impact actions always confirm.** `run_shell` (when enabled),
  `install_package` and `delete_path` call `permissions.confirm`, which fails
  closed (denied if no dialog or no answer within 60 s).
- **Ambiguity is never guessed.** When a target could be several apps/games,
  windows or panes the assistant asks instead of acting; destructive tools are
  never invoked on a guess.
- **Precise desktop actions are identity-checked.** `close_window` and
  `close_tmux_pane` act only on a Hyprland window `address` / tmux `pane_id`, show
  the exact target, confirm, then revalidate the identity and abort if it changed
  or closed. `list_windows` / `list_tmux_panes` are read-only. The model can never
  invent an address, pane id, pid or selection, and cannot close a different
  object than the one shown. Focus is treated as distinct from an in-app selection.
- **Selection context is local and honest.** The selected/active object inside an
  application is read via AT-SPI when the application exposes it; otherwise the
  assistant reports it unavailable and asks. A name from `get_selection` is not
  treated as a file path. Reading a file's *contents* (`read_document`) is off by
  default, requires an absolute path, is size-bounded, shows the canonical path,
  and returns the text as untrusted data — never as instructions to follow.
- **Selected-file paths are verified, not guessed.** A file manager's selection is
  read from the XDG primary selection's `text/uri-list` (local `file://` URIs only,
  canonicalized, must exist); several selected items are reported ambiguous and the
  assistant asks. `open_selected` opens the single verified path with the default
  handler only after confirmation and revalidation. A selected item's *name* is
  never treated as a path.
- **Process control is exact and conservative.** Process identity is `(pid, start
  time)`, so a reused PID is detected; command lines are redacted of secret-looking
  flags and environments are never read. Stopping a process requires confirmation,
  revalidates the identity, sends **SIGTERM only** (never `SIGKILL`/`pkill -f`/kill
  by port/name), and owning a port never authorizes stopping its owner. Logs are
  bounded and treated as untrusted data that cannot trigger tools.
- **Service lifecycle is registry-gated.** Start/stop/restart work only for services
  the user registered by hand in `services.json` (read-only to the assistant) with a
  validated argv command; there is no shell and no invented command. A managed launch
  records the child's `(pid, start time)`, which is revalidated before any later
  action; a reused PID is treated as no managed runtime. Ownership is the direct child
  only (no tree kill), `SIGTERM` only (never `SIGKILL`), confirmation is required, and
  a service is never restarted when its stop failed or its definition changed.
  `service_lifecycle: false` disables the state-changing operations.
- **A central policy authorizes every call before it runs (`policy.py`).** The model
  interprets language and proposes a tool; Python decides whether the exact call may
  execute. `dispatch_tool` rejects unknown tools, missing/oversized required
  arguments, and any tool whose capability is disabled — before the tool body runs,
  and a denial never falls through to another path. No tool is trusted merely
  because its description says "read-only".
- **Service targets are resolved deterministically.** A request resolves to a
  registered service **id** or an explicit registered **alias** only; a human label
  is never matched, so "backend" cannot silently become a frontend. Missing targets
  are reported as missing, alias collisions as ambiguous, and neither substitutes a
  different service. `run_shell` can no longer be used to start a service by default
  (see `shell_control`).

### Tool authorization inventory (`policy.py`)

| Category | Tools | Confirmation | Revalidates target |
|---|---|---|---|
| read | `list_*`, `inspect_*`, `get_selection`, `capture_tmux_pane`, `service_logs`, `recall`, `list_notes` | no | n/a |
| reversible | `open_app`, `launch_steam_game`, `web_search`, `save_note`, `remember`, `launch_opencode` | no | n/a |
| confirmed | `close_app`, `close_window`, `close_tmux_pane`, `open_selected`, `stop_process`, `start_service`, `stop_service`, `restart_service`, `install_package`, `delete_path`, `run_shell` | yes | window address / pane id / file path / `(pid,starttime)` / service spec hash |

Capability gates: `shell_control`→`run_shell`; `process_control`→`stop_process`;
`service_lifecycle`→service start/stop/restart; `document_read`→`read_document`.
- **Notes and web results are data, not instructions.** Saved notes are only read
  back as text; the assistant does not fetch or execute web content at all, and a
  tool result can never change permissions.
- **`shell=True` is used only by `run_shell`.** Every other subprocess uses an
  argument vector. `run_shell` is unique because the user explicitly approved an
  arbitrary command (pipes, redirection).

## Local by default

- Speech recognition (whisper.cpp) and inference (Ollama) run on `127.0.0.1`.
- The Ollama URL defaults to loopback. Do not point it at a remote host unless
  you understand that your prompts will leave the machine.
- The only network feature is `web_search`, which opens your browser on a search
  URL. The query leaves the machine; nothing is read back.
- No telemetry, no accounts, no cloud APIs.

## Filesystem and processes

- The assistant only writes under its own data/runtime directories by default.
- `close_app` closes windows via the compositor; it only sends `SIGTERM` to a
  process after you approve, and now confirms before closing an app's windows.
- `close_window` / `close_tmux_pane` close exactly one window/pane by identity
  after confirmation and revalidation (never a broad `pkill` or `kill -9`).
- `delete_path` moves files to the trash with `gio trash` (reversible).
- Nothing here escalates privileges. `install_package` opens a terminal so *you*
  type your own password; hyprwhispr never handles credentials.

## Audit log and privacy defaults

Every tool call, approval and denial is appended to
`<data>/logs/audit.jsonl` with a timestamp, tool name, status and duration.
Tool **arguments are not logged by default** (`log_tool_args`), and transcript
text is **not written** to `exchanges.log` by default (`log_transcripts`). Each
turn also appends timing metrics (steps, call counts, per-stage durations and
Ollama token counts) — numbers only, never prompts, transcripts or model output.
The short-lived conversation context in `<data>/state/session.json` is bounded,
expires, and is created with owner-only permissions. Nothing is sent anywhere.

## Reporting a vulnerability

See `SECURITY.md`.
