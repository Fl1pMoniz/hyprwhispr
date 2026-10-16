# Architecture

hyprwhispr is one Python package (standard library only) that drives two local
engines: whisper.cpp (speech-to-text) and Ollama (the language model).

```
        hold SUPER+V                         release SUPER+V
             │                                     │
             ▼                                     ▼
   ┌───────────────────┐                 ┌───────────────────┐
   │ hyprwhispr        │                 │ hyprwhispr        │
   │ record-start      │                 │ record-stop       │
   └─────────┬─────────┘                 └─────────┬─────────┘
             │ spawns pw-record                    │ stop; duration+silence gate
             ▼                                     ▼
   ┌───────────────────┐                 ┌───────────────────────┐
   │  microphone       │                 │  worker: "process"    │
   │  (PipeWire)       │                 └───────────┬───────────┘
   └───────────────────┘                             │
                          ┌──────────────────────────┼──────────────────────────┐
                          ▼                          ▼                          ▼
                 ┌─────────────────┐       ┌──────────────────┐       ┌──────────────────┐
                 │ whisper.cpp     │       │ agent loop       │       │ tool dispatch    │
                 │ (local STT)     │       │ (Ollama chat)    │       │ (+ confirm gate) │
                 └─────────────────┘       └──────────────────┘       └──────────────────┘
                          │                          │                          │
                          └──────── transcript ─────┘                          │
                                                     │                          │
                                            final text answer ─────────────────┘
                                                     ▼
                                          notify-send (text only)
```

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | XDG paths, default settings, load/save config, `now()` |
| `notify.py` | `notify-send` wrapper and the local JSONL audit log |
| `permissions.py` | the confirmation gate (`zenity`/`rofi`, fails closed after 60 s) |
| `validation.py` | argument validators (length, package-name shape) |
| `audio.py` | microphone capture, WAV probe (duration/peak), `list-mics`, `mictest` |
| `speech.py` | whisper.cpp invocation, GPU→CPU fallback, transcript cleanup |
| `llm.py` | Ollama client, agent loop, tool-call parsing/sanitisation, timing |
| `tools.py` | the tool registry (JSON schemas) and `dispatch_tool` |
| `power.py` | activation flag (`is_enabled`) plus safe model release (`unload_if_idle`, `recording_active`) |
| `desktop.py` | verified Hyprland window + tmux pane context, and precisely-targeted, confirmed actions |
| `selection.py` | optional AT-SPI selection/active-object context (helper process) + bounded `read_document` |
| `processes.py` | process/socket/project discovery from `/proc` with stable `(pid, starttime)` identity and confirmed `stop_process` |
| `services.py` | hand-written service registry, status/readiness, and confirmed start/stop/restart of registered services |
| `policy.py` | central tool-execution policy: tool categories, capability gates, required-argument validation |
| `discovery.py` | capability check: is a usable executable available (configured → PATH → candidates), with a short bounded cache |
| `browsers.py` | browser discovery and safe URL opening (`browser_bin`, common browsers, `xdg-open`/`gio` fallback) |
| `apps.py` | `.desktop` + Steam indexing, normalization, resolve/launch/close |
| `memory.py` | notes and remembered preferences (persistent) |
| `session.py` | bounded, expiring conversation context (temporary) |
| `web.py` | the single network feature: open a browser search |
| `system_actions.py` | confirmation-gated shell / install / delete |
| `cli.py` | command-line entry point and text rendering |

## Request lifecycle

1. **Press**: the compositor runs `hyprwhispr record-start`; a `pw-record`
   subprocess writes 16 kHz mono WAV and its pid is saved.
2. **Release**: `record-stop` stops the recorder, then checks the clip with
   `audio.probe_wav`. A clip shorter than `min_record_ms`, or quieter than
   `silence_threshold_db`, is rejected before whisper runs (this removes the
   silence-hallucination class of bugs). Otherwise a detached worker
   (`python -m hyprwhispr process <file>`) does the slow work.
3. **Transcribe**: `speech.transcribe` runs whisper.cpp with `-l auto` (or an
   explicit language code from config), so the spoken language is detected and
   the transcript stays in that language — never translated. CUDA is used with a
   CPU fallback on a GPU error; the transcript is cleaned and its temporary files
   are removed. The transcript is passed to the model unchanged.
4. **Agent loop** (`llm.run_pipeline`): builds messages from the system prompt,
   configured aliases, *relevant* remembered preferences (`memory.relevant_context`),
   the last referenced target with a freshness note, a bounded log of recent tool
   actions and their outcomes (`session.activity_context`), and recent
   conversation history, then repeatedly:
   - asks the model (native function calling, or a strict JSON tool protocol),
   - if tools are requested, validates and executes them, feeding the **actual**
     results back,
   - stops when the model answers with text, or when `max_tool_steps` is reached
     (then asks for a plain-text answer with tools disabled).
5. **Guard rails**: duplicate identical tool calls are suppressed; unknown tools
   and malformed arguments become error results the model must react to. A tool
   is only requested by machine tool-call syntax (native calls, a `<tool_call>`
   block, a fenced `json` block, or content that is itself a JSON object) — a
   tool named only in prose is never executed. The model can never claim success
   without a confirming tool result.
6. **Reply** (`llm.clean_answer`): chain-of-thought blocks and any leaked
   tool-call markup or bare tool-call JSON are stripped from the final text, so
   internal data is never shown to the user. If nothing user-facing remains, the
   loop makes **one bounded retry** asking for plain text and then falls back to
   a short safe message. `session` records the turn and the referenced target so
   follow-ups ("close it") resolve, and the text is shown with `notify-send`.

## Timing and observability

Each turn appends one `turn` record to the local audit log with stage timings
and counts only — never prompts, transcripts or model output:

- `steps`, `llm_calls`, `tool_calls`;
- `llm_ms` (summed Ollama request time), `tool_ms` (tool execution), `total_ms`;
- `llm_call_ms` (per-request durations);
- `llm_prompt_tokens` / `llm_eval_tokens` / `llm_load_ms` (Ollama's non-content
  response fields).

Transcription is timed separately (a `transcribe` record), and the detached
worker logs a `pipeline_total`. All durations use a monotonic clock.
`scripts/benchmark.py` aggregates the same metrics across a fixed request set and
reports median/p95 with sample counts; an optional `max_tokens` cap bounds
worst-case generation latency (measure first — low caps hurt tool selection).

## Desktop context and target resolution

Natural-language understanding stays with the model; identity and safety stay in
Python. Each turn may include a compact, verified "focused window" note
(`desktop.context_line`, gated by `desktop_context`). The model reasons over that
plus `list_windows` / `list_tmux_panes` output and picks a target:

1. interpret the request (model);
2. discover candidate targets (Python, read-only);
3. choose the intended object (model, from verified candidates);
4. validate the chosen identity and, for destructive actions, confirm the exact
   target (Python);
5. revalidate the identity and execute against that exact object (Python).

A Hyprland window `address` and a tmux `pane_id` are the identities; titles and
classes are only hints. If several candidates fit, or the selection is inside an
application (a file, tab or document), the model asks instead of guessing, and
`desktop.py` never fabricates an address, pane id, pid or selection. Focus can
change while the model thinks, so `close_window` / `close_tmux_pane` revalidate
after confirmation and abort if the target moved or closed.

Stage 3 adds optional **selection** context (`selection.py`): the selected object
inside an application, read from AT-SPI. Because the standard-library venv cannot
import `gi`, the AT-SPI read runs in a bounded helper process under an interpreter
that can, and returns one JSON object; the main program parses it and labels the
value `selected` / `active` / `displayed`, `verified` or not. When no provider is
available the context is `unavailable` and the model asks. Reading file contents
is a separate opt-in action (`document_read`) whose output is labelled untrusted.

Stage 3.1 adds **verified file paths**: the XDG primary selection's `text/uri-list`
(a file manager offers the selected files' `file://` URIs there) is read with
`wl-paste`, parsed with `urllib`, canonicalized, and accepted only as a single
existing local file; several selections are reported ambiguous. This is kept as a
separate provider (`source: primary-selection`) from the AT-SPI name/text, so the
two are never merged into one target.

Stage 4 adds **process/project awareness** (`processes.py`). Discovery reads
`/proc/<pid>/stat` (parsing the parenthesised command name safely) for identity
``(pid, starttime)``, `/proc/<pid>/fd` + `/proc/net/*` for listening sockets, and
the focused tmux pane / window working directory for the project root (marker-based,
walking up). The LLM reasons over read-only results and may call `stop_process` with
an exact `id`; Python confirms, revalidates the identity against fresh `/proc` data,
and sends SIGTERM only. Nothing is killed by name or port, and PID reuse is
detected because the start time is part of the identity.

Stage 5 adds **service lifecycle management** (`services.py`) on top of that. A
hand-written registry (`services.json`) maps ids to validated definitions
(project root, cwd inside it, an argv command, timeouts, an optional readiness
port and log path). The assistant only reads it. A managed launch records the
child's identity durably; status is derived from that identity plus the configured
readiness port (owned by the process); start/stop/restart are confirmed and
revalidate both the definition and the runtime identity, send `SIGTERM` only, and
never manage unregistered or externally-started processes.

Stage 6 adds the authorization boundary: `policy.py` classifies every tool
(read/reversible/confirmed), declares capability gates, and validates required
arguments; `tools.dispatch_tool` consults it **before** any tool body runs, so a
model call that is unknown, malformed, or gated is refused and never falls through.
Service targets resolve only by exact id or registered alias (labels are not
identity), and arbitrary command execution (`run_shell`) is off by default and
separated from the service manager.

## Power and model residency

HyprWhispr is a one-shot CLI, not a daemon. `record-start` spawns a detached
recorder; `record-stop` stops it and spawns a detached ``process`` worker that
transcribes, runs the agent turn and exits. `ask`/`listen` run in the invoking
process. The only long-running process is the optional foreground
``wake-word listen`` loop. Nothing autostarts.

Because there is no daemon, "power" is a persistent ``enabled`` flag
(``config.py``): when off, `power.require_enabled` makes assistant turns refuse to
run, ``record_start``/``listen``/``wake-word listen`` decline, and ``power off``
releases the model once no recording is active. Enabling never loads the model;
the first request does. Unloading reuses ``llm.unload_model`` + ``/api/ps`` and
never stops the Ollama server. Coordination is best-effort: the flag lives in the
config file (updated atomically) and the only activity signal is the recorder
pidfile — a detached inference worker is not tracked, so ``power off`` may race a
turn that is already inferring (the model is simply reloaded next time).

## Model lifetime

The model's memory lifetime follows Ollama's `keep_alive` (config key
`keep_alive`, default `5m`). `cli.model_command` exposes `model status`,
`model keep-alive <auto|always|0|dur>` and `model unload`; `unload` issues a
`/api/generate` request with `keep_alive: 0` and confirms the result with
`/api/ps`. Unloading is always an explicit, user-driven action: it is never
triggered between agent-loop steps, it never stops the Ollama server, and it never
deletes weights. Each turn is a separate short-lived worker, so no daemon is
needed; `model unload` refuses (best effort) while a recording is in progress.

## Model compatibility

Native Ollama tool calling is preferred. `llm.ollama_chat` raises
`ToolsUnsupported` when a server rejects a request carrying tool schemas; the
loop then switches to a **constrained JSON tool protocol** (the model replies
with `{"tool": ..., "arguments": {...}}`), which is parsed strictly: only a
`<tool_call>` block, a fenced `json` block, or content that is itself a JSON
object naming a registered tool is accepted, and the arguments are coerced to an
object. A JSON object embedded in ordinary prose is ignored, so free text is
never mistaken for a tool call. `tool_mode` can force `native` or `json`.

The tool executor (`tools.dispatch_tool`) is independent of the model
provider, so another local model or server can be substituted without touching
the tools.

## Why these choices

- **Structured tool calling, not regex dispatch.** The model returns typed JSON
  arguments; nothing is parsed out of free text. Deterministic code still owns
  validation, ambiguity detection and permissions.
- **One worker process per turn.** A crash in transcription or inference never
  takes down the compositor binding, and the key release stays instant.
- **A file, not a database, for context.** The session is small, bounded,
  atomically written, and expires; persistent memory lives separately.
- **Discover, do not assume.** Launching a browser, app, terminal, Steam game or
  OpenCode first resolves an executable (`discovery.py`: configured value, then
  `PATH`, then documented candidates). Discovery is a capability check, never an
  authorisation, and never a shell.
- **Everything local.** Whisper and the model run on this machine; the only
  socket is Ollama on loopback, and the only browser call is an explicit search.
