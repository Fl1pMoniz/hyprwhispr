# hyprwhispr

A local, **hold-to-talk** desktop assistant for Hyprland. Hold a key, speak in
your language, release, and read a short text answer. Speech recognition and language
inference run entirely on your machine.

```
hold SUPER+V  →  speak  →  release  →  text answer
```

hyprwhispr is a thin, readable glue layer between tools you already run:
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) for speech-to-text and
[Ollama](https://ollama.com) for the language model. It is Python, standard
library only, and small enough to read in an afternoon.

> Status: usable and tested, but young. See `CHANGELOG.md`.

## Ukraine support 🇺🇦

HyprWhispr is built to work in **Ukrainian**, not just English:

- 🇺🇦 **Speech and replies** — the multilingual model recognises Ukrainian and the
  assistant answers in Ukrainian; Ukrainian is exercised end-to-end by the language
  tests (`tests/test_multilingual.py`).
- **Ukrainian by default around activation** — the default wake word is the
  Ukrainian exclamation `дідько` ("the devil", a mild and tongue-in-cheek curse),
  and 🇺🇦 Ukrainian sits in the language list.
- **Local and private** — recognition and inference run on your machine; no audio
  or text is sent to a cloud service.

Слава Україні! 🇺🇦 пізда російській педерації

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
- **Local multilingual speech-to-text** with whisper.cpp (multilingual `small`),
  CUDA or CPU, with a silence/short-record gate and automatic GPU→CPU fallback.
- **Automatic language detection** — speak 🇵🇹 Portuguese, 🇺🇦 Ukrainian,
  🇬🇧 English, 🇪🇸 Spanish, 🇫🇷 French, 🇩🇪 German, 🇮🇹 Italian, 🇸🇦 Arabic,
  🇯🇵 Japanese, 🇨🇳 Chinese and more; whisper detects the language and the reply
  stays in it. Pin a language with `"language": "pt"`.
- **Optional wake word** — activate hands-free with a configurable phrase
  (disabled by default; the Ukrainian default is `дідько`). Detected locally by
  reusing whisper (no training) or the optional lower-CPU openWakeWord engine. See
  [docs/wake-word.md](docs/wake-word.md).
- **Local inference** through Ollama, with a configurable model (default
  `qwen3:4b`).
- **Natural-language tool calling** — varied phrasing ("can you bring up my
  browser?", "I'm done playing, shut Steam down") maps to the right tool via
  native function calling, with a strict JSON fallback for models without it.
- **Safe, clean output** — a tool is only run by machine tool-call syntax (never
  by prose that merely mentions it), and leaked tool-call markup or JSON is
  stripped from replies, with a bounded retry if no user text remains.
- **Conversation context** — follow-ups like "now close it" resolve against a
  bounded, expiring local session (not a database). Recent tool calls and their
  real outcomes are remembered across the separate worker processes, remembered
  targets carry a freshness note, and only relevant preferences are injected.
- **Model memory controls** — keep the model warm, unload it after a configurable
  idle time, keep it loaded, or release it on demand (`model ...`, see below).
- **Power switch** — `power on`/`power off` enable or disable the assistant and
  release the model when idle; enabling does not load the model.
- **Ambiguity handling** — when several apps match, it asks instead of guessing,
  and remembers the choices for the next turn.
- **Launch and close apps and Steam games** by name, discovered from your
  installed `.desktop` files and Steam library (no hard-coded allow-list).
- **Web search** that opens your browser (the only feature that uses the network).
- **Discovers programs instead of assuming them** — the browser, terminal, Steam
  and OpenCode are resolved from your config, then `PATH`, then common names
  (`browser_bin` picks a preferred browser); a missing program gives a clear
  error instead of a failure, and discovery never bypasses the safety checks.
- **Notes and preferences** stored locally as plain files.
- **Confirmation gates** for shell commands, package installs and file deletion.
- **Audit log** of tool name, status and duration, plus per-turn timing metrics
  (numbers only); arguments and transcripts are not logged by default.
- **OpenCode integration** by launching it (optionally with a prepared prompt).
- Microphone helpers: `list-mics`, `mictest`, and a terminal `listen` mode.
- A repeatable **tool-selection benchmark** (`scripts/benchmark.py`).

## Architecture

See [`docs/architecture.md`](docs/architecture.md). In short: a key press spawns
`pw-record`; the key release stops it, applies a silence/short-record gate, and
starts a detached worker that runs whisper.cpp, then the Ollama **agent loop**
(with typed tools, duplicate-call suppression, ambiguity detection and a bounded
step budget), then shows the answer with `notify-send`. Follow-ups resolve
against a small, expiring session file.

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

## Installation

### Fedora / Nobara (recommended)

```bash
git clone https://github.com/Fl1pMoniz/hyprwhispr.git
cd hyprwhispr
./scripts/install.sh
```

The installer detects your system, prints a PASS/WARN/FAIL summary of what is
missing, and then — with your confirmation — does as much as it safely can:

- installs missing system packages with `dnf` (`pipewire-utils`, `libnotify`,
  `pipx`, build tools, and optional helpers);
- installs the `hyprwhispr` Python app with `pipx` (or a virtualenv fallback);
- pulls the Ollama model, builds whisper.cpp at a pinned revision, and downloads
  the multilingual Whisper model (both verified by checksum);
- creates `~/.config/hyprwhispr/config.json` **only if it is missing** and writes
  a Hyprland binding **snippet** only if you confirm.

It is idempotent: re-running it reuses what already works and changes nothing else.

| Flag                  | Effect                                                    |
| --------------------- | --------------------------------------------------------- |
| `--check`             | Read-only dependency report (PASS/WARN/FAIL)              |
| `--dry-run`           | Show exactly what would happen, changing nothing          |
| `--yes`               | Non-interactive: accept the supported prompts             |
| `--no-model-download` | Skip the Ollama and Whisper model downloads               |
| `--with-wake-word`    | Also install the optional wake-word engine (openWakeWord) |
| `--help`              | Usage                                                     |

**Automatic:** Fedora/Nobara packages, the Python app, and the local models.
**Never:** installing a desktop environment, overwriting your config, editing your
Hyprland configuration, or running remote scripts as root.
**May need you:** installing Ollama itself
(https://ollama.com/download/linux) and adding the Hyprland keybinding.

**Supported:** Fedora Workstation, Fedora with Hyprland, and Nobara, using `dnf`.
Fedora-derived systems using `dnf` are treated as Fedora (untested). **Not
supported:** Fedora Atomic / image-based variants (Silverblue, Kinoite, Bazzite,
…) — the installer stops and points you to `rpm-ostree`/toolbox; and non-Fedora
distributions, where it exits without making changes.

After installing:

```bash
scripts/verify.sh          # runtime dependency check
hyprwhispr listen 6        # record, transcribe, answer (after login)
```

### Manual installation (any Fedora/Nobara)

```bash
git clone https://github.com/Fl1pMoniz/hyprwhispr.git
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
(https://ollama.com/download/linux) — the installer and setup script tell you it
is missing rather than running a remote installer for you.

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

- Whisper `ggml-small.bin` — the **multilingual** model (supports automatic
  language detection), downloaded from the upstream whisper.cpp Hugging Face
  repository by `scripts/download-models.sh`, which verifies a pinned SHA-256.
  OpenAI Whisper weights are MIT-licensed; the ggml conversion is distributed by
  the whisper.cpp project. The English-only `ggml-small.en.bin` is still available
  as an alternative (`WHISPER_MODEL_NAME=ggml-small.en.bin`).
- `qwen3:4b` — pulled through Ollama from Ollama's registry; the Qwen3 weights
  are Apache-2.0.

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for details and caveats.

## Configuration and usage

Configuration lives in `~/.config/hyprwhispr/config.json`. Start from
`examples/config.example.json`; every key has a sensible default. Full reference:
[`docs/configuration.md`](docs/configuration.md).

### Languages

Speech recognition speaks many languages out of the box: whisper auto-detects the
spoken language and the transcript (and the reply) stay in it — no per-language
setup. This needs the multilingual model (`ggml-small.bin`, the default).

```jsonc
"language": null      // default: detect the spoken language automatically
"language": "en"      // force English 🇬🇧
"language": "pt"      // force Portuguese 🇵🇹
"language": "uk"      // force Ukrainian 🇺🇦
```

Any short ISO-639 code whisper supports is passed straight through, so switching
languages needs no code change. To return to automatic detection, set
`"language": null` (or remove the key). If you set an explicit English-only model
(`ggml-small.en.bin`) with `"language": null`, the assistant logs a warning because
that model cannot detect other languages.

Common tasks:

```bash
hyprwhispr listen 6          # record 6s, print transcript + answer (quick test)
hyprwhispr ask "what is 2+2" # type instead of speaking
hyprwhispr list-mics         # find your microphone
hyprwhispr mictest           # check the input level
hyprwhispr model small       # switch to the smaller model
hyprwhispr power status      # on/off state, activity and model status
hyprwhispr model status      # model, memory policy and whether it is loaded
hyprwhispr model unload      # release the model's memory now
hyprwhispr apps firefox      # search installed apps
hyprwhispr games hollow      # search installed Steam games
hyprwhispr refresh-apps      # rebuild app/game indexes
```

### VRAM (hardware-specific example)

These are **measurements on one machine** (NVIDIA RTX 4070 12 GB, `qwen3:4b`,
`small` on GPU) made with
`nvidia-smi --query-compute-apps=process_name,used_memory --format=csv`:

| State                                 | Approx. VRAM held by hyprwhispr |
| ------------------------------------- | ------------------------------- |
| Idle, model unloaded                  | 0 MiB                           |
| Idle, model warm (`keep_alive`)       | ~3.2 GB                         |
| During transcription (whisper on GPU) | ~1 GB, transient                |

Your numbers will differ with model, context size and driver. To reduce usage:
`hyprwhispr model small`, `"whisper_gpu": false`, and a shorter `keep_alive`.

### Power (on/off) and turning the model off

HyprWhispr is **not a daemon**: each request (push-to-talk, `ask`, `listen`, the
optional `wake-word listen`) starts a process and exits. There is nothing to
"start" or "stop", so `power` is a persistent **enabled switch**, kept separate
from whether the model is loaded:

```bash
hyprwhispr power status   # enabled state, activity, and model status
hyprwhispr power on       # allow requests (does NOT load the model)
hyprwhispr power off      # refuse new requests and release the model when safe
```

`power on` only flips the switch; the model still loads on the first real request.
`power off` persists the disabled state, refuses new push-to-talk/`ask`/`listen`/
wake-word requests (recording is declined too), and — once no recording is in
progress — asks Ollama to release the configured model. It never stops the Ollama
server, never touches other applications' models, and never claims VRAM was freed
(it reports what `/api/ps` confirms). `power status` and `power on` keep working
while the assistant is off.

Disabling HyprWhispr is different from unloading the model (`model unload`) and
from stopping Ollama (`systemctl --user stop ollama`): `power off` is the
assistant's own switch.

### Model memory (keep-alive and unloading)

The local model can either stay warm for fast follow-ups or be released when you
are done. This is Ollama's `keep_alive`, exposed as one setting and three commands:

```bash
hyprwhispr model status              # model, policy, loaded state (via /api/ps)
hyprwhispr model keep-alive auto     # unload after 5m idle (default)
hyprwhispr model keep-alive always   # stay loaded (uses memory while idle)
hyprwhispr model keep-alive 10m      # unload after 10m idle
hyprwhispr model unload              # release the model's memory now
```

`unload` asks Ollama to drop the model and verifies it with `/api/ps`; it never
stops the Ollama service and never deletes weights. Because memory reclamation
depends on the Ollama version, backend and GPU driver, the reported size is
*observed*, not a guarantee. Keeping the model loaded cuts the next request's
latency but holds RAM/VRAM while idle.

### Latency

Reply latency is dominated by how many tokens the local model generates (measured:
turn time tracks generated tokens; model loading and tool calls are negligible).
Each turn logs per-stage timings (total, LLM, tool, per-call and token counts) —
numbers only. Investigate with `python scripts/benchmark.py --live`, and bound
worst-case generation with the optional `"max_tokens"` setting: **measure first**,
because a low cap trades tool-selection accuracy for speed.

### Wake word (optional)

Disabled by default. Enable hands-free activation with a configurable phrase (the
default is `дідько`):

```bash
hyprwhispr wake-word set "дідько"     # change the phrase (does not enable it)
hyprwhispr wake-word enable         # mode = both (keeps the keyboard shortcut)
hyprwhispr wake-word listen         # run the listener in the foreground
hyprwhispr wake-word disable        # back to shortcut-only
```

Detection is fully local and only runs while `wake-word listen` is running (no
daemon or autostart). The default engine reuses your local whisper.cpp model, so
the default `дідько` — and other languages/phrases — work **without any training**;
an optional lower-CPU openWakeWord engine is available for its supported English
phrases. Details, licensing and accuracy caveats:
[docs/wake-word.md](docs/wake-word.md).

### Browsers and other programs

HyprWhispr never assumes a specific browser, terminal or app exists. When it needs
to launch one it resolves an executable: your configured value first, then `PATH`,
then a short list of common names. If none is found it says so plainly instead of
failing silently.

- Browser: set `"browser_bin": "firefox"` (or any executable name/path) to choose
  one; leave it empty to auto-detect, with `xdg-open`/`gio` as a last resort.
- Terminal: `terminal_bin` (default `kitty`) falls back through `foot`,
  `alacritty`, `wezterm`, `konsole`, `gnome-terminal`, ...
- `scripts/verify.sh` reports which of these were found and checks your
  configured `whisper_bin`/`whisper_model`, not just the default paths.

Discovery only checks that a program exists; it never grants permission to run it,
and all launches still use an argument vector (never a shell).

## Commands

| Command                                        | Purpose                                      |
| ---------------------------------------------- | -------------------------------------------- |
| `record-start` / `record-stop`                 | the push-to-talk pair used by the keybinding |
| `ask <text>`                                   | run the model + tools on typed text          |
| `listen [sec]`                                 | record, transcribe, answer (terminal test)   |
| `transcribe <wav>` / `process <wav>`           | speech-to-text only / full pipeline          |
| `read`                                         | show the last exchange                       |
| `apps` / `games` / `launch` / `play` / `close` | application and game control                 |
| `resolve <query>`                              | show which apps/games match a query (debug)  |
| `session` / `session clear`                    | show or clear the conversation context       |
| `power status` / `power on` / `power off`      | enable/disable the assistant and its model   |
| `refresh-apps`                                 | rebuild the app and Steam indexes            |
| `list-mics` / `mictest`                        | microphone helpers                           |
| `model [small\|large\|name]`                   | show or set the model                        |
| `model status` / `model keep-alive <policy>`   | memory-lifetime policy and loaded state      |
| `model unload`                                 | release the model's memory now               |
| `version`                                      | print the version                            |

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

The suite runs against an isolated temporary data directory and uses mocks and a
scripted fake model, so it never touches your real desktop, microphone or GPU.
`scripts/verify.sh` checks the local runtime dependencies.

### Benchmark

`scripts/benchmark.py` measures tool selection over a fixed set of **text**
requests (`tests/eval/requests.json`) — including multilingual fixtures. It runs
offline by default (harness check) and against the real local model with
`--live`; in both cases tools are recorded, never executed:

```bash
python scripts/benchmark.py                     # harness, no model
python scripts/benchmark.py --live              # real local model
python scripts/benchmark.py --transcribe a.wav  # time one transcription
python scripts/benchmark.py --wer manifest.json # word error rate vs references
```

It reports tool-selection accuracy (overall and multilingual subset), argument
accuracy, clarification rate, unsafe-action rate, LLM calls per task, latency
(median / p95 with sample counts and a per-stage total/LLM/tool breakdown), and -
for a live model - whether non-Latin replies use the expected script.

**Scope:** the text fixtures measure the _assistant_, not speech recognition (no
audio or Whisper is involved). Transcription is measured separately with
`--transcribe`, and word error rate only with `--wer` and a manifest that pairs
local recordings with reference transcripts. Script checks can confirm a writing
system but not that an answer is grammatical or truly in the requested language.

## Troubleshooting

See [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Uninstall

```bash
scripts/uninstall.sh                 # removes data + config (asks first)
pipx uninstall hyprwhispr            # or: pip uninstall hyprwhispr
```

Then remove the hold-to-talk binding (and any `~/.config/hypr/hyprwhispr.conf`
snippet and its `source =` line the installer may have written) and reload:
`hyprctl reload`. Uninstalling never removes Ollama, its models, or OpenCode.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Contributions are welcome; keep changes
small, tested and honest.

## License

MIT — see [`LICENSE`](LICENSE). Third-party components and model licences are
listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md), with the evidence,
uncertainties and provenance caveats recorded in
[`docs/license-audit.md`](docs/license-audit.md). Run `scripts/audit.sh` for a
lightweight hygiene/dependency check (it cannot prove provenance or compliance).

Note: the source was authored with AI assistance; see the provenance section of
`THIRD_PARTY_NOTICES.md`.
