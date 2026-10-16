# Configuration

hyprwhispr reads a single JSON file:

```
~/.config/hyprwhispr/config.json
```

Start from `examples/config.example.json`. Any key you omit falls back to the
built-in default, so a minimal file is fine.

You can point the whole program somewhere else (useful for testing) with
environment variables:

| Variable | Meaning |
|---|---|
| `HYPRWHISPR_CONFIG` | full path to the config file |
| `HYPRWHISPR_DATA` | data directory (whisper.cpp, models, notes, cache, state) |
| `HYPRWHISPR_RUNTIME` | runtime directory (recording while in use) |

## Activation

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | master on/off switch. Change it with `hyprwhispr power on` / `power off` |

`enabled` is written with an atomic read-modify-write (`config.update_config`) so
it does not clobber other settings, and a missing key means enabled (existing
configs keep working). Being enabled does **not** load the model: that happens on
the first real request. `power off` refuses new assistant requests and recordings
and releases the model when no recording is in progress. See the Power section of
the README.

## Inference

| Key | Default | Meaning |
|---|---|---|
| `ollama_url` | `http://127.0.0.1:11434` | local Ollama server (keep it on loopback) |
| `model` | `qwen3:4b` | model name (see `hyprwhispr model`) |
| `model_aliases` | `{"small": "qwen3:4b", "large": "qwen3:8b"}` | names accepted by `hyprwhispr model <alias>` |
| `keep_alive` | `5m` | how long Ollama keeps the model in memory/VRAM after a turn. Set it with `hyprwhispr model keep-alive <auto\|always\|0\|10m>`; `-1` keeps it loaded until changed |
| `num_ctx` | `4096` | context window |
| `temperature` | `0.3` | sampling temperature |
| `max_tokens` | `null` | optional cap on generated tokens per reply (Ollama `num_predict`); `null` = no cap. Bounds worst-case latency but can truncate and hurt tool selection at low values - test with `scripts/benchmark.py` first |
| `request_timeout` | `120` | seconds allowed per model request |
| `max_tool_steps` | `5` | agent-loop iterations before the model is forced to answer |
| `tool_mode` | `auto` | `auto` (native function calling, JSON fallback), `native`, or `json` |

## Model lifetime and memory

Ollama keeps a model in memory for `keep_alive` after the last use. hyprwhispr
exposes this policy with one setting and a few commands:

```
hyprwhispr model status              # model, policy, and whether it is loaded
hyprwhispr model keep-alive auto     # unload after 5m idle (default)
hyprwhispr model keep-alive always   # stay loaded until changed or unloaded
hyprwhispr model keep-alive 10m      # unload after 10m idle
hyprwhispr model unload              # release the model's memory now
```

Trade-off: keeping the model loaded removes the reload latency from the next
request but consumes RAM/VRAM the whole time it is idle. `unload` asks Ollama to
drop the model (`keep_alive: 0`) and checks `/api/ps`; it never stops the Ollama
service and never deletes weights. Whether memory is actually reclaimed depends on
the Ollama version, backend and GPU driver, so `model status` shows the size
Ollama *reports* as observed information, not a promise.

A policy of `0` is applied **after the whole turn finishes** - including any tool
calls and follow-up model requests - never between an intermediate request and the
next one, so a multi-step turn never reloads the model mid-way. A non-zero policy
(`5m`, `10m`, `always`) keeps the model warm between turns.

## Speech recognition

| Key | Default | Meaning |
|---|---|---|
| `whisper_bin` | `<data>/whisper.cpp/build/bin/whisper-cli` | whisper.cpp binary |
| `whisper_model` | `<data>/models/ggml-small.bin` | multilingual ggml model (supports auto detection) |
| `whisper_gpu` | `true` | use CUDA; on a GPU error it retries on the CPU |
| `whisper_timeout` | `120` | seconds before a transcription is aborted |
| `language` | `null` | spoken language: `null`/`"auto"` to detect, or a code like `"en"`/`"pt"` |

### Languages

`language` is `null` by default, so whisper.cpp **auto-detects** the spoken
language (`-l auto`) and the transcript stays in that language — the reply does
too. This requires the multilingual model; the old English-only
`ggml-small.en.bin` cannot detect other languages (set `whisper_model` back to it
only if you always speak English).

- Automatic (default): `"language": null` (or omit the key, or `"auto"`).
- Force a language: `"language": "en"`, `"language": "pt"`, `"language": "uk"`,
  `"language": "ja"`, ... Any short ISO-639 code that whisper supports is passed
  straight through, so there is no application-side language list to maintain.
- Invalid values (e.g. `"english"`) are rejected with a clear error before
  whisper runs.

Transcription never translates: the `-tr`/`--translate` flag is not used, so a
Portuguese recording yields a Portuguese transcript.

## Audio capture

| Key | Default | Meaning |
|---|---|---|
| `sample_rate` | `16000` | recorder sample rate (leave at 16000 for Whisper) |
| `recorder` | `pw-record` | capture command (`parecord` for PulseAudio) |
| `mic_target` | `null` | specific input device node name, or `null` for the system default |
| `min_record_ms` | `300` | holds shorter than this are treated as an accidental tap |
| `silence_threshold_db` | `-50` | a peak below this is treated as silence and skipped |
| `keep_recordings` | `false` | keep the recorded `.wav` after processing |

## Conversation context

| Key | Default | Meaning |
|---|---|---|
| `history_turns` | `6` | user+assistant turns kept for the model |
| `session_ttl_minutes` | `30` | context is forgotten after this idle time |
| `action_history` | `8` | recent tool calls remembered in the session (for follow-ups and truthfulness) |
| `app_ambiguity_margin` | `150` | score gap below which app matches are treated as ambiguous |

## Integrations

| Key | Default | Meaning |
|---|---|---|
| `apps` | small map | launch aliases (e.g. `"terminal": "kitty"`) checked before auto-discovery |
| `browser_bin` | `""` (auto) | preferred browser executable (name or absolute path). Empty = detect a common browser on `PATH`, then fall back to `xdg-open`/`gio` |
| `search_url` | `https://duckduckgo.com/?q=` | web-search prefix (e.g. Google, SearXNG) |
| `opencode_bin` | `opencode` | path to the OpenCode executable |
| `terminal_bin` | `kitty` | preferred terminal emulator (falls back to `foot`, `alacritty`, `wezterm`, `konsole`, ...) |
| `tool_timeout` | `60` | seconds allowed for a confirmed shell command |

## Privacy / logging

| Key | Default | Meaning |
|---|---|---|
| `log_transcripts` | `false` | write transcript text to `exchanges.log` (off by default) |
| `log_tool_args` | `false` | write tool arguments to `audit.jsonl` (off by default) |

## Choosing a microphone

By default hyprwhispr records from the system default source. To pin a device:

```
hyprwhispr list-mics
wpctl inspect <id> | grep node.name     # copy the value
```

then set it:

```json
{ "mic_target": "alsa_input.usb-Your_Headset-00.mono-fallback" }
```

Use `hyprwhispr mictest` to confirm the device actually captures sound; a peak
level much below about −50 dBFS will be treated as silence.

## Choosing a model and VRAM

`hyprwhispr model` prints the current model; `hyprwhispr model small`,
`hyprwhispr model large`, or `hyprwhispr model <name>` sets it. Smaller models
use less VRAM. VRAM figures are hardware-specific; measure your own with:

```
nvidia-smi --query-compute-apps=process_name,used_memory --format=csv
```

If you are tight on VRAM, set `"whisper_gpu": false` to move speech recognition
to the CPU and shorten `keep_alive` so the model unloads sooner when idle.

## Conversation context

Each push-to-talk recording starts a fresh worker, so context is kept in a small
bounded JSON file (`<data>/state/session.json`) that expires after
`session_ttl_minutes`. It holds the recent user/assistant turns, the most recently
referenced target (with a timestamp, so the model is told it may be stale), and a
bounded log of recent tool calls and their outcomes (`action_history`). Inspect or
clear it with:

```
hyprwhispr session
hyprwhispr session clear
```

Only *relevant* persistent preferences are added to a prompt
(`memory.relevant_context`), so a large preferences file does not flood every
request. Persistent preferences and notes are separate and permanent (see
`docs/tools.md`). Sensitive tool arguments (shell commands, package names, file
paths) are recorded as status only, never as text.
