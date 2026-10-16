# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Central tool-execution policy and authorization hardening (Stage 6).** New
  `policy.py` classifies every registered tool (read-only / reversible / confirmed)
  and declares capability gates; `tools.dispatch_tool` consults it **before** any
  tool body runs, rejecting unknown tools, missing/oversized required arguments, and
  disabled capabilities, with no fall-through path. Service targets now resolve only
  by exact registered **id** or an explicit registered **alias** (a human label is
  never matched), returning structured `ok`/`missing`/`ambiguous` results so a
  requested-but-unregistered service (e.g. "backend" with only "frontend"
  registered) is never silently substituted. Arbitrary shell execution (`run_shell`)
  is now gated by the new `shell_control` capability and **off by default**, so a
  service cannot be started through the shell. Registry entries gained an optional
  `aliases` list. Confirmation continues to bind the exact target and revalidate
  identity, and lifetime/definition changes abort the action.
- **Development-service lifecycle management (Stage 5).** New `services.py` with a
  small, **hand-written** service registry (`services.json` next to `config.json`;
  `HYPRWHISPR_SERVICES` override) that the assistant only reads. Definitions are
  validated (absolute canonical `project_root`/`cwd` with cwd inside the root, an
  argv `command` whose executable resolves, bounded timeouts, optional readiness
  port and in-project log path). Read-only tools `list_services`, `inspect_service`,
  `service_logs`; confirmed lifecycle tools `start_service`, `stop_service`,
  `restart_service`. A managed start records the child's `(pid, start time)`
  identity durably and revalidates it against `/proc` before later actions (PID
  reuse is detected; ownership is the direct child only). Status is
  STOPPED/STARTING/RUNNING/UNHEALTHY/UNKNOWN with evidence (a port is never proof on
  its own). Launches use an argv with a minimal environment and no shell; stop is
  `SIGTERM` only; restart aborts on a changed definition or a failed stop. Config:
  `service_lifecycle` (default true). Unregistered services, command discovery from
  a project, and systemd/Docker orchestration are intentionally not supported.
- **Development process/project awareness (Stage 4).** New `processes.py` discovers
  local development processes and listening sockets from `/proc` and `/proc/net`
  (no new dependency, no shell), with a stable identity of `(pid, kernel start
  time)` so a reused PID is detected and refused. Read-only tools: `list_processes`,
  `inspect_process`, `list_listening_ports`, `inspect_project_services` (project
  root found conservatively from focused tmux/window context via markers; services
  are processes whose working directory is inside the root), and
  `capture_tmux_pane` (bounded, untrusted output). Command lines are redacted of
  secret-looking flags and environments are never read. The confirmation-gated
  `stop_process` stops exactly one process by id: it revalidates the identity, sends
  **SIGTERM only**, waits a bounded 5 s and never escalates to `SIGKILL`, `pkill -f`
  or kill-by-port. Config: `process_control` (default true). Starting/restarting
  services and process-tree kills are intentionally not implemented.
- **Verified selected-file paths (Stage 3.1).** A selected file-manager item is now
  resolved to a real filesystem path via the XDG primary selection's
  `text/uri-list` (read with `wl-clipboard`); `file://` URIs are parsed with
  `urllib`, canonicalized, and accepted only as a single existing local file —
  other schemes/hosts are rejected and several selected items are reported as
  ambiguous rather than picked. `get_selection` reports the verified path
  (`source: primary-selection`) separately from the AT-SPI name/text, and the new
  confirmation-gated `open_selected` opens the single verified file. Config:
  `selection_clipboard` (default true). The system prompt now tells the model to
  call `get_selection` before asking the user and to use a verified path rather
  than a name.
- **Selection context (Stage 3, optional).** New `selection.py` reads the object
  the user has selected or has active inside the focused application (selected
  text, a selected item/file name, an active browser tab, or a displayed document)
  via **AT-SPI**. A short-lived helper process runs under a Python that has
  PyGObject, so the standard-library venv stays dependency-free. Context is
  labelled `selected`/`active`/`displayed` and `verified`, and reported
  `unavailable`/`unsupported` rather than guessed when the provider is missing
  (accessibility disabled, `pyatspi` absent, or a sandboxed app off the bus). New
  read-only tool `get_selection`, and opt-in `read_document` (disabled unless
  `document_read` is true) that reads a bounded local file as untrusted data.
  Config: `selection_context` (default true), `a11y_python` (default auto), and
  `document_read` (default false).
- **Natural-language desktop targets (windows and tmux).** New `desktop.py` reads
  verified Hyprland window context (focused window, open windows with their stable
  `address`) and resolves the tmux pane shown in the focused terminal from the
  window's process tree (not the `TMUX` environment). New tools: read-only
  `list_windows` / `list_tmux_panes`, and confirmation-gated `close_window` /
  `close_tmux_pane` that show the exact target, then **revalidate** its identity
  and abort if it changed or disappeared. `close_app` now also confirms before
  closing windows. Each turn may include a compact focused-window note
  (`desktop_context`, default on). The model interprets the request; identity and
  safety stay in Python - it never invents an address/pane id/selection, and focus
  is treated as distinct from an in-app selection. Requires Hyprland (`hyprctl`)
  and, for panes, `tmux`; unavailable integrations fail clearly.
- **On/off control (`hyprwhispr power`).** `power status` reports the enabled
  state, recording activity and model status (reusing `model status`); `power on`
  flips a persistent `enabled` switch without loading the model; `power off`
  refuses new push-to-talk/`ask`/`listen`/wake-word requests and recordings, then
  releases the configured model once no recording is in progress. It never stops
  the Ollama server or touches other models, and it reports only what `/api/ps`
  confirms. The flag is stored in the existing config via an atomic
  read-modify-write (`config.update_config`) that preserves all other keys; a
  missing key means enabled, so existing configs keep working. Recordings, the
  wake-word listener and assistant turns all respect the disabled state.
- **Program discovery before launching.** Browser opening and application,
  terminal, Steam and OpenCode launches now verify that a suitable executable
  exists (user-configured value first, then `PATH`, then a small documented
  candidate list) rather than assuming a specific program. Adds the `browser_bin`
  setting, returns clear structured errors when nothing is available, and never
  routes launches through a shell. Discovery is a capability check only - the
  existing permission/confirmation gates are unchanged.
- **Multi-step turns no longer risk unloading the model.** A `keep_alive` policy
  of `0` is applied only after the whole turn finishes (tool calls and follow-up
  inference included), never between an intermediate tool call and the next
  request. A non-zero policy avoids cross-turn reloads entirely.
- **`scripts/verify.sh` respects the effective configuration**: it checks the
  configured `whisper_bin`/`whisper_model` (with a `PATH` fallback) instead of
  only the default data-dir path - fixing a false "Whisper missing" report - and
  additionally reports browser and terminal availability without running them.
- **Better conversation context.** Tool calls and their real outcomes are now
  persisted in the bounded session file (`session.record_action` /
  `activity_context`), so a later worker process sees what was actually done -
  including failures - instead of only the final reply. Remembered targets carry a
  freshness note, and only *relevant* persistent preferences are injected per
  request (`memory.relevant_context`) rather than every stored fact. The session
  file stays backward compatible and sensitive tool arguments are not persisted.
- **Model memory lifecycle.** New `hyprwhispr model status`,
  `model keep-alive <auto|always|0|10m>` and `model unload` commands. The policy
  is validated (`config.validate_keep_alive`) and stored in the existing
  `keep_alive` key (no second setting); `unload` asks Ollama to release the model
  with `keep_alive: 0` and verifies it via `/api/ps` - it never stops the Ollama
  server and never deletes weights. Model status reports the loaded state and
  observed memory size (observed only, not a guarantee).
- **Optional wake word** (disabled by default). Activation modes `shortcut`
  (default), `wake_word`, `both`, `disabled`; a configurable phrase stored verbatim
  with the exact Ukrainian default `дідько` (disabled; a mild, humorous curse); a pluggable detector interface with **two**
  backends — a default **whisper** engine that reuses the local whisper.cpp model
  (any language/phrase such as `дідько`, no training needed, higher CPU) and an
  optional lower-CPU **openWakeWord** engine (English pretrained or custom-trained
  model) — selected via `wake_word_engine` (`auto`/`whisper`/`openwakeword`); a
  foreground `wake-word listen` loop with no daemon and one-stage/two-stage
  interaction; capability reporting that truthfully distinguishes engine support;
  the new `wake-word` CLI (`show`/`set`/`enable`/`disable`/`mode`/`check`/`listen`)
  and an opt-in installer flag `--with-wake-word`. Detection is local; no audio
  leaves the machine.
- **Fedora/Nobara installer** (`scripts/install.sh`): guided, idempotent setup
  with `--check` (read-only report), `--dry-run`, `--yes` and
  `--no-model-download`. It detects Fedora, Nobara, Fedora-derived and Atomic
  variants, installs missing `dnf` packages, the Python app (pipx or a venv
  fallback), the Ollama and Whisper models, whisper.cpp, the config, and offers a
  Hyprland binding snippet - without ever overwriting config or editing Hyprland.
  Atomic variants and non-Fedora systems are refused without changes.
- **Automatic multilingual speech recognition.** Default model is now the
  multilingual `ggml-small.bin` and `language` defaults to `null` (whisper's
  built-in auto-detection, `-l auto`). Speak Portuguese, Ukrainian, English,
  Spanish and other languages without per-language configuration; the transcript
  and reply stay in the spoken language (transcription mode is used, never
  translation). Ukrainian verified (`-l uk`, LLM replies in Ukrainian) and added
  as a documented example and benchmark fixture.
- `speech.resolve_language` / `speech.build_command` with a format check for
  explicit language codes (any short ISO-639 code is passed through to whisper).
- Benchmark extensions: multilingual fixtures (pt/es/de/it/ar/ja/zh), a separate
  transcription-latency mode (`--transcribe FILE.wav`), a multilingual-subset
  accuracy line, a script-based answer-language signal for non-Latin replies, a
  per-stage latency breakdown (total/LLM/tool/per-call), and optional word-error
  rate over local recordings (`--wer MANIFEST`).
- Optional `max_tokens` config (Ollama `num_predict`) to cap generated tokens per
  reply; `null` by default. Capping bounds worst-case latency but can hurt
  tool-selection accuracy at low values - measure with the benchmark first.
- Per-turn timing instrumentation (total, LLM, tool, per-call durations, and
  prompt/eval token counts) recorded in the audit log with no transcript content.

### Changed
- `scripts/download-models.sh` defaults to the multilingual model, downloads to a
  `.part` file, verifies the pinned SHA-256, and only then installs it; the
  English-only `ggml-small.en.bin` remains available via `WHISPER_MODEL_NAME`.
- `scripts/verify.sh` checks for the multilingual model and warns if only the
  English-only model is present.
- Ollama system prompt instructs the assistant to reply in the user's language.
- Tool-call JSON is only parsed from clear machine syntax (`<tool_call>` blocks, a
  fenced `json` block, or content that is itself a JSON object); a JSON object
  embedded in prose is no longer executed.

### Fixed
- Strip leaked `<tool_call>` markup and bare tool-call JSON envelopes from a reply
  so a model that echoes a tool call as text can no longer show raw JSON to the
  user; when nothing user-facing remains, make one bounded retry and then fall
  back to a short safe message.
- `scripts/benchmark.py` no longer leaves a patched model in the process after a
  fake-mode run (it now always restores `llm.ollama_chat`).

## [1.1.0] - 2026-10-16

Natural-language intelligence, reliable tool calling, context and speech-quality
overhaul.

### Added
- **Conversation context**: a small, bounded, expiring session (`session.py`) so
  follow-ups such as "now close it" resolve against the recent turn and the last
  referenced app/game. New `session` and `session clear` commands.
- **Ambiguity handling**: when several apps/games match with no clear winner,
  `open_app`/`close_app` ask instead of guessing; choices are remembered for the
  next turn. New `resolve <query>` command to inspect ranked candidates.
- **Runtime-compatibility fallback**: `ToolsUnsupported` triggers a strict
  constrained-JSON tool protocol for servers/models without native tool calling
  (`tool_mode` = `auto` | `native` | `json`).
- **Speech robustness**: silence and short-record gates (`min_record_ms`,
  `silence_threshold_db`), transcription cleanup, and automatic GPU→CPU
  fallback on CUDA errors.
- **Benchmark harness** (`scripts/benchmark.py`) over `tests/eval/requests.json`
  with tool-selection/argument accuracy, clarification and unsafe-action
  metrics, and latency percentiles.
- Config options: `request_timeout`, `max_tool_steps`, `tool_mode`,
  `model_aliases`, `whisper_timeout`, `min_record_ms`, `silence_threshold_db`,
  `keep_recordings`, `history_turns`, `session_ttl_minutes`,
  `app_ambiguity_margin`, `tool_timeout`, `log_transcripts`, `log_tool_args`.

### Changed
- Agent loop: bounded steps, duplicate tool-call suppression, per-call timings,
  forced plain-text answer when the budget is exhausted, and explicit errors for
  unknown tools / malformed arguments.
- App/game resolution: Unicode and punctuation normalization, filler-word
  filtering, ranked candidates, configured alias matching on tokens, and
  `ambiguous:` results.
- Privacy defaults: transcripts and tool arguments are no longer written to logs
  unless explicitly enabled.
- `recall` with no key lists everything remembered.
- Recording files are cleaned up after processing unless `keep_recordings` is set.

### Documentation and compliance
- Added `docs/license-audit.md`: an evidence-based license/provenance audit with
  verified upstream licenses, uncertainties and the AI-assisted-provenance caveat.
- Corrected `THIRD_PARTY_NOTICES.md`: **libnotify is LGPL-2.1** (was stated as
  MIT), completed the invoked-only tool inventory, and stated the AI-provenance
  caveat honestly instead of claiming the code is untainted.
- Added `scripts/audit.sh`, a dependency-free hygiene/dependency inventory.

### Tests
- Added session, speech, audio-probe, agent-loop and benchmark tests; suite grew
  from 40 to 82 tests.

## [1.0.0] - 2026-10-16

Initial release.

### Added
- Hold-to-talk voice input on Hyprland via `record-start` / `record-stop`
  bindings.
- Local English speech-to-text with whisper.cpp (CUDA or CPU).
- Local inference through Ollama (default `qwen3:4b`), text-only replies.
- Tool calling with typed JSON schemas for: opening/closing apps and Steam
  games, listing apps and games, web search, notes, remembered preferences,
  launching OpenCode, and confirmation-gated shell/install/delete actions.
- Dynamic application and Steam discovery from `.desktop` files and
  `appmanifest_*.acf` libraries.
- Confirmation gate (`zenity`/`rofi`) that fails closed, plus a local JSONL
  audit log.
- Microphone helpers (`list-mics`, `mictest`) and a terminal `listen` mode.
- Setup, verification and uninstall scripts; unit and security test suite.
