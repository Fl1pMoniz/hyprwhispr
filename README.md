# hyprwhispr

A local, **hold-to-talk** desktop assistant for Hyprland. Hold a key, speak in
English, release, and read a short text answer. Speech recognition and language
inference run entirely on your machine.

```
hold SUPER+V  →  speak  →  release  →  text answer
```

hyprwhispr is a thin, readable glue layer between tools you already run:
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) for speech-to-text and
[Ollama](https://ollama.com) for the language model. It is Python, standard
library only, and small enough to read in an afternoon.

> Status: usable and tested, but young. See `CHANGELOG.md`.

## Goals and design principles

- **Local-first.** No cloud speech recognition, no cloud LLM, no telemetry.
- **Press-and-hold, not a toggle.** Recording starts on key press and stops on
  key release.
- **Text-only.** No text-to-speech is used or required.
- **Small and understandable.** One package, no third-party Python dependencies,
  clear module boundaries.
- **Safe by construction.** The model picks typed tools; state-changing tools
  ask for confirmation and fail closed.
- **Honest.** The README describes only what is implemented and tested.

## Features

- Global **hold-to-talk** binding on Hyprland (`bind` + `bindr`).
- **Local English speech-to-text** with whisper.cpp (`small.en`), CUDA or CPU.
- **Local inference** through Ollama, with a configurable model (default
  `qwen3:4b`).
- **Answer questions** with the local model; replies are plain text.
- **Launch and close apps and Steam games** by name, discovered from your
  installed `.desktop` files and Steam library (no hard-coded allow-list).
- **Web search** that opens your browser (the only feature that uses the network).
- **Notes and preferences** stored locally as plain files.
- **Confirmation gates** for shell commands, package installs and file deletion.
- **Audit log** of every tool call.
- **OpenCode integration** by launching it (optionally with a prepared prompt).
- Microphone helpers: `list-mics`, `mictest`, and a terminal `listen` mode.

## Architecture

See [`docs/architecture.md`](docs/architecture.md). In short: a key press spawns
`pw-record`; the key release stops it and starts a detached worker that runs
whisper.cpp, then the Ollama agent loop (with tools), then shows the answer with
`notify-send`.

## Requirements

- Linux with a Wayland compositor that supports press/release binds
  (**Hyprland** is the tested target).
- **PipeWire** (or PulseAudio) and a working microphone.
- **Python 3.9+**.
- **Ollama**, running locally.
- **whisper.cpp** built locally (helper script provided).
- Optional but recommended: `libnotify` (`notify-send`), `gtk-launch`,
  `zenity` or `rofi` (for confirmations), `ffmpeg` (for `mictest` levels).
- A CUDA toolkit is optional; without it whisper.cpp builds CPU-only.

Tested on Nobara/Fedora 44 with Hyprland. Other compositors are supported only if
they provide equivalent press/release keybindings.

## Installation (from a fresh checkout)

```bash
git clone https://github.com/<you>/hyprwhispr.git
cd hyprwhispr

# 1. Install the Python package (no runtime dependencies).
pipx install .          # recommended
# or:  python3 -m venv .venv && . .venv/bin/activate && pip install .

# 2. Language model + engines (all local).
scripts/setup-ollama.sh       # pulls the model; does not install Ollama itself
scripts/setup-whisper.sh      # clones + builds whisper.cpp (CUDA if available)
scripts/download-models.sh    # downloads + checksums the Whisper model

# 3. Configuration.
mkdir -p ~/.config/hyprwhispr
cp examples/config.example.json ~/.config/hyprwhispr/config.json

# 4. Check everything is present.
scripts/verify.sh
```

If Ollama is not installed, get it from its official Linux page
(https://ollama.com/download/linux) — the setup script will tell you if it is
missing rather than running a remote installer for you.

### Bind hold-to-talk in Hyprland

Add the press/release pair to your Hyprland config and reload:

**hyprlang** (see `examples/hyprland-keybinds.conf`):

```
bind  = SUPER, V, exec, hyprwhispr record-start
bindr = SUPER, V, exec, hyprwhispr record-stop
```

**Lua config** (e.g. KoolDots, see `examples/hyprland-keybinds.lua`):

```lua
hl.bind("SUPER + V", hl.dsp.exec_cmd("hyprwhispr record-start"), { description = "hold to talk" })
hl.bind("SUPER + V", hl.dsp.exec_cmd("hyprwhispr record-stop"),  { description = "release to send", release = true })
```

Then `hyprctl reload`. Pick any unused key combination.

## Model downloads and licensing

Models are **downloaded at setup time and are not part of this repository**.

- Whisper `ggml-small.en.bin` — downloaded from the upstream whisper.cpp Hugging
  Face repository by `scripts/download-models.sh`, which verifies a pinned
  SHA-256. OpenAI Whisper weights are MIT-licensed; the ggml conversion is
  distributed by the whisper.cpp project.
- `qwen3:4b` — pulled through Ollama from Ollama's registry; the Qwen3 weights
  are Apache-2.0.

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for details and caveats.

## Configuration and usage

Configuration lives in `~/.config/hyprwhispr/config.json`. Start from
`examples/config.example.json`; every key has a sensible default. Full reference:
[`docs/configuration.md`](docs/configuration.md).

Common tasks:

```bash
hyprwhispr listen 6          # record 6s, print transcript + answer (quick test)
hyprwhispr ask "what is 2+2" # type instead of speaking
hyprwhispr list-mics         # find your microphone
hyprwhispr mictest           # check the input level
hyprwhispr model small       # switch to the smaller model
hyprwhispr apps firefox      # search installed apps
hyprwhispr games hollow      # search installed Steam games
hyprwhispr refresh-apps      # rebuild app/game indexes
```

### VRAM (hardware-specific example)

These are **measurements on one machine** (NVIDIA RTX 4070 12 GB, `qwen3:4b`,
`small.en` on GPU) made with
`nvidia-smi --query-compute-apps=process_name,used_memory --format=csv`:

| State | Approx. VRAM held by hyprwhispr |
|---|---|
| Idle, model unloaded | 0 MiB |
| Idle, model warm (`keep_alive`) | ~3.2 GB |
| During transcription (whisper on GPU) | ~1 GB, transient |

Your numbers will differ with model, context size and driver. To reduce usage:
`hyprwhispr model small`, `"whisper_gpu": false`, and a shorter `keep_alive`.

## Commands

| Command | Purpose |
|---|---|
| `record-start` / `record-stop` | the push-to-talk pair used by the keybinding |
| `ask <text>` | run the model + tools on typed text |
| `listen [sec]` | record, transcribe, answer (terminal test) |
| `transcribe <wav>` / `process <wav>` | speech-to-text only / full pipeline |
| `read` | show the last exchange |
| `apps` / `games` / `launch` / `play` / `close` | application and game control |
| `refresh-apps` | rebuild the app and Steam indexes |
| `list-mics` / `mictest` | microphone helpers |
| `model [small\|large\|name]` | show or set the model |
| `version` | print the version |

Tools the model can call are documented in [`docs/tools.md`](docs/tools.md).

## Security

The assistant only reaches the network for an explicit web search. Speech and
inference stay local. Shell, package-install and delete actions always require a
confirmation dialog and fail closed. See [`docs/security.md`](docs/security.md).

## Testing and development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest
pytest -q
```

The suite runs against an isolated temporary data directory and uses mocks, so it
never touches your real desktop. `scripts/verify.sh` checks the local runtime
dependencies.

## Troubleshooting

See [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Uninstall

```bash
scripts/uninstall.sh                 # removes data + config (asks first)
pipx uninstall hyprwhispr            # or: pip uninstall hyprwhispr
```

Then remove the binding from your Hyprland config and `hyprctl reload`. Ollama,
its models, and OpenCode are not touched.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Contributions are welcome; keep changes
small, tested and honest.

## License

MIT — see [`LICENSE`](LICENSE). Third-party components and model licences are
listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
