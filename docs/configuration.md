# Configuration

hyprwhispr reads a single JSON file:

```
~/.config/hyprwhispr/config.json
```

You can start from `examples/config.example.json`. Any key you omit falls back
to the built-in default, so a minimal file is fine.

You can point the whole program somewhere else (useful for testing) with
environment variables:

| Variable | Meaning |
|---|---|
| `HYPRWHISPR_CONFIG` | full path to the config file |
| `HYPRWHISPR_DATA` | data directory (whisper.cpp, models, notes, cache) |
| `HYPRWHISPR_RUNTIME` | runtime directory (recording while in use) |

## Keys

| Key | Default | Meaning |
|---|---|---|
| `ollama_url` | `http://127.0.0.1:11434` | local Ollama server (keep it on loopback) |
| `model` | `qwen3:4b` | model name (see `hyprwhispr model`) |
| `keep_alive` | `5m` | how long Ollama keeps the model in VRAM after a turn |
| `num_ctx` | `4096` | context window |
| `temperature` | `0.3` | sampling temperature |
| `whisper_bin` | `<data>/whisper.cpp/build/bin/whisper-cli` | whisper.cpp binary |
| `whisper_model` | `<data>/models/ggml-small.en.bin` | ggml model file |
| `whisper_gpu` | `true` | use CUDA; set `false` to transcribe on the CPU |
| `language` | `en` | speech-recognition language |
| `sample_rate` | `16000` | recorder sample rate (leave at 16000 for Whisper) |
| `recorder` | `pw-record` | capture command (`parecord` for PulseAudio) |
| `mic_target` | `null` | specific input device node name, or `null` for the system default |
| `apps` | small map | launch aliases (e.g. `"terminal": "kitty"`) checked before auto-discovery |
| `search_url` | `https://duckduckgo.com/?q=` | web-search prefix (e.g. Google, SearXNG) |
| `opencode_bin` | `opencode` | path to the OpenCode executable |
| `terminal_bin` | `kitty` | terminal used for OpenCode and installs |

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

Use `hyprwhispr mictest` to confirm the device actually captures sound.

## Choosing a model and VRAM

`hyprwhispr model` prints the current model; `hyprwhispr model small`,
`hyprwhispr model large`, or `hyprwhispr model <name>` sets it. Smaller models
use less VRAM. VRAM figures are hardware-specific; measure your own with:

```
nvidia-smi --query-compute-apps=process_name,used_memory --format=csv
```

If you are tight on VRAM, set `"whisper_gpu": false` to move speech recognition
to the CPU and shorten `keep_alive` so the model unloads sooner when idle.
