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

## Inference

| Key | Default | Meaning |
|---|---|---|
| `ollama_url` | `http://127.0.0.1:11434` | local Ollama server (keep it on loopback) |
| `model` | `qwen3:4b` | model name (see `hyprwhispr model`) |
| `model_aliases` | `{"small": "qwen3:4b", "large": "qwen3:8b"}` | names accepted by `hyprwhispr model <alias>` |
| `keep_alive` | `5m` | how long Ollama keeps the model in VRAM after a turn |
| `num_ctx` | `4096` | context window |
| `temperature` | `0.3` | sampling temperature |
| `max_tokens` | `null` | optional cap on generated tokens per reply (Ollama `num_predict`); `null` = no cap. Bounds worst-case latency but can truncate and hurt tool selection at low values - test with `scripts/benchmark.py` first |
| `request_timeout` | `120` | seconds allowed per model request |
| `max_tool_steps` | `5` | agent-loop iterations before the model is forced to answer |
| `tool_mode` | `auto` | `auto` (native function calling, JSON fallback), `native`, or `json` |

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
- Force a language: `"language": "en"`, `"language": "pt"`, `"language": "ja"`, ...
  Any short ISO-639 code that whisper supports is passed straight through, so
  there is no application-side language list to maintain.
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
| `app_ambiguity_margin` | `150` | score gap below which app matches are treated as ambiguous |

## Integrations

| Key | Default | Meaning |
|---|---|---|
| `apps` | small map | launch aliases (e.g. `"terminal": "kitty"`) checked before auto-discovery |
| `search_url` | `https://duckduckgo.com/?q=` | web-search prefix (e.g. Google, SearXNG) |
| `opencode_bin` | `opencode` | path to the OpenCode executable |
| `terminal_bin` | `kitty` | terminal used for OpenCode and installs |
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
`session_ttl_minutes`. Inspect or clear it with:

```
hyprwhispr session
hyprwhispr session clear
```

Persistent preferences and notes are separate and permanent (see
`docs/tools.md`).
