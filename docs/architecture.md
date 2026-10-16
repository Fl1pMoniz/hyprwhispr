# Architecture

hyprwhispr is deliberately small: one Python package (standard library only),
plus two external local engines driven as subprocesses or over an HTTP API.

```
        hold SUPER+V                         release SUPER+V
             │                                     │
             ▼                                     ▼
   ┌───────────────────┐                 ┌───────────────────┐
   │ hyprwhispr        │                 │ hyprwhispr        │
   │ record-start      │                 │ record-stop       │
   └─────────┬─────────┘                 └─────────┬─────────┘
             │ spawns pw-record                    │ stops pw-record,
             ▼                                     │ spawns worker
   ┌───────────────────┐                           ▼
   │  microphone       │                 ┌───────────────────────┐
   │  (PipeWire)       │                 │  worker: "process"    │
   └───────────────────┘                 └───────────┬───────────┘
                                                     │
                          ┌──────────────────────────┼──────────────────────────┐
                          ▼                          ▼                          ▼
                 ┌─────────────────┐       ┌──────────────────┐       ┌──────────────────┐
                 │ whisper.cpp     │       │ Ollama HTTP API  │       │ tool dispatch    │
                 │ (local STT)     │       │ (local LLM)      │       │ (+ confirm gate) │
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
| `audio.py` | microphone capture with `pw-record`; `list-mics`, `mictest` |
| `speech.py` | whisper.cpp invocation and transcript cleanup |
| `llm.py` | Ollama chat client, the agent loop, and thinking-block cleanup |
| `tools.py` | the tool registry (JSON schemas) and `dispatch_tool` |
| `apps.py` | `.desktop` + Steam game indexing, resolve/launch/close |
| `memory.py` | notes and remembered preferences |
| `web.py` | the single network feature: open a browser search |
| `system_actions.py` | confirmation-gated shell / install / delete |
| `cli.py` | command-line entry point and text rendering |

## Request lifecycle

1. **Press**: the compositor runs `hyprwhispr record-start`. A `pw-record`
   subprocess starts writing 16 kHz mono WAV to the runtime directory, and its
   pid is saved. A "Listening..." notification appears.
2. **Release**: the compositor runs `hyprwhispr record-stop`. The recorder gets
   `SIGINT` (which finalises the WAV), then a detached worker
   (`python -m hyprwhispr process <file>`) does the slow work so the key release
   returns instantly.
3. **Transcribe**: the worker calls `whisper-cli` (whisper.cpp) on the WAV.
4. **Answer**: the transcript is sent to the local Ollama server together with
   the tool schemas and the remembered-preferences block.
5. **Tools**: if the model requests a tool, `dispatch_tool` validates and runs it.
   Safe tools run immediately; high-impact tools call `permissions.confirm`.
   Results are fed back to the model in a bounded loop (max 5 steps).
6. **Reply**: the final text is shown with `notify-send` and saved to the runtime
   directory and the exchange log.

## Why these choices

- **Structured tool calling, not regex dispatch.** The model returns typed JSON
  arguments; nothing is parsed out of free text, which avoids injection through
  the transcript.
- **One worker process per turn.** A crash in transcription or inference can
  never take down the compositor binding, and the key release is instant.
- **Everything local.** Whisper and the LLM run on this machine. The only socket
  used is Ollama on loopback; the only browser call is an explicit web search.
