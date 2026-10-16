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
   configured aliases, remembered preferences, recent conversation history and
   the last referenced target, then repeatedly:
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
- **Everything local.** Whisper and the model run on this machine; the only
  socket is Ollama on loopback, and the only browser call is an explicit search.
