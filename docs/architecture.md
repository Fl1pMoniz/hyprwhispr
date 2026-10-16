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
| `llm.py` | Ollama client, the agent loop, JSON-tool fallback, thinking cleanup |
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
3. **Transcribe**: `speech.transcribe` runs whisper.cpp (CUDA, falling back to
   CPU on a GPU error), cleans the transcript, and removes its temporary files.
4. **Agent loop** (`llm.run_pipeline`): builds messages from the system prompt,
   configured aliases, remembered preferences, recent conversation history and
   the last referenced target, then repeatedly:
   - asks the model (native function calling, or a strict JSON tool protocol),
   - if tools are requested, validates and executes them, feeding the **actual**
     results back,
   - stops when the model answers with text, or when `max_tool_steps` is reached
     (then asks for a plain-text answer with tools disabled).
5. **Guard rails**: duplicate identical tool calls are suppressed; unknown tools
   and malformed arguments become error results the model must react to; the
   model can never claim success without a confirming tool result.
6. **Reply**: the text is shown with `notify-send`. `session` records the turn
   and the referenced target so follow-ups ("close it") resolve.

## Model compatibility

Native Ollama tool calling is preferred. `llm.ollama_chat` raises
`ToolsUnsupported` when a server rejects a request carrying tool schemas; the
loop then switches to a **constrained JSON tool protocol** (the model replies
with `{"tool": ..., "arguments": {...}}`), which is parsed strictly — only a
JSON object naming a registered tool is accepted, so ordinary answers are never
mistaken for a tool call. `tool_mode` can force `native` or `json`.

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
