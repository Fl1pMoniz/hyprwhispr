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
- **Notes and web results are data, not instructions.** Saved notes are only read
  back as text; the assistant does not fetch or execute web content at all.

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

## Audit log

Every tool call, approval and denial is appended to
`<data>/logs/audit.jsonl` with a timestamp. Arguments are logged as given;
no secrets are collected by the assistant.

## Reporting a vulnerability

See `SECURITY.md`.
