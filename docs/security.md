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
  arbitrary command — and it always asks first.
- **High-impact actions always confirm.** `run_shell`, `install_package` and
  `delete_path` call `permissions.confirm`, which fails closed (denied if no
  dialog or no answer within 60 s).
- **Ambiguity is never guessed.** When a target could be several apps/games the
  assistant asks instead of acting; destructive tools are never invoked on a
  guess.
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
  process after you approve.
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
