# Third-Party Notices

hyprwhispr's **own source code** is licensed under the MIT License (see
`LICENSE`).

The repository does **not** bundle third-party source code, model weights,
binaries or fonts. Everything else is either *invoked as an external program*
already installed on the user's system, *downloaded and built locally at setup
time*, or *pulled as model weights through Ollama* — all under the user's
control, none redistributed here.

Model-weight licences are **separate** from software licences: a permissively
licensed runtime (whisper.cpp, Ollama) does **not** grant rights over the weights
it loads. This file separates the two.

> A detailed, evidence-based audit (with upstream license quotes, uncertainties
> and the AI-provenance caveat) is in [`docs/license-audit.md`](docs/license-audit.md).

## Software invoked at runtime (not distributed, not linked)

hyprwhispr calls these programs as external processes. It does not link against
or redistribute them, so their licences impose no notice obligation on this
repository; they are listed for transparency.

| Component | Used for | License | Source |
|---|---|---|---|
| PipeWire (`pw-record`, `wpctl`) | microphone capture, device listing | MIT | https://pipewire.org |
| Hyprland (`hyprctl`) | window list / close windows | BSD-3-Clause | https://github.com/hyprwm/Hyprland |
| libnotify (`notify-send`) | desktop notifications | LGPL-2.1 | https://gitlab.gnome.org/GNOME/libnotify |
| zenity | confirmation dialog (preferred) | LGPL-2.1 (verify upstream) | https://gitlab.gnome.org/GNOME/zenity |
| rofi | confirmation dialog (fallback) | MIT/X11 | https://github.com/davatorium/rofi |
| GLib (`gio`) | move files to the trash | LGPL-2.1-or-later | https://gitlab.gnome.org/GNOME/glib |
| GTK (`gtk-launch`) | launch `.desktop` apps | LGPL-2.1-or-later | https://gitlab.gnome.org/GNOME/gtk |
| ffmpeg | microphone level analysis (`mictest`) | LGPL-2.1-or-later or GPL (build-dependent) | https://ffmpeg.org |
| xdg-utils (`xdg-open`) | open a browser search | MIT | https://freedesktop.org/wiki/Software/xdg-utils/ |
| wl-clipboard (`wl-copy`) | copy a prepared prompt | GPL-3.0 | https://github.com/bugaevc/wl-clipboard |
| procps (`pgrep`, `pkill`) | find/terminate a process on close | GPL-2.0-or-later | https://gitlab.com/procps-ng/procps |
| kitty | terminal launch (OpenCode, installs) | GPL-3.0 | https://github.com/kovidgoyal/kitty |
| OpenCode | optional coding agent | MIT | https://github.com/sst/opencode |
| Steam | launch/close Steam games | proprietary (Valve) | https://store.steampowered.com |

## Software downloaded and built locally (not redistributed)

| Component | Used for | Pinned revision | License | Source |
|---|---|---|---|---|
| **whisper.cpp** | local speech-to-text engine | commit `0c7be696371069e0baa2515ed7aa08d5a5473aa6` | MIT ("Copyright (c) 2023-2026 The ggml authors") | https://github.com/ggml-org/whisper.cpp |
| **ggml** (bundled inside whisper.cpp) | tensor backend for whisper.cpp | same checkout | MIT (covered by whisper.cpp's `LICENSE`, which names the ggml authors) | https://github.com/ggml-org/ggml |

`scripts/setup-whisper.sh` clones whisper.cpp at the pinned commit and builds it
in the user's data directory. It is not committed here.

## Model weights (downloaded by the user, not redistributed)

| Artifact | Source | Pinned | License | Evidence |
|---|---|---|---|---|
| `ggml-small.en.bin` (Whisper `small.en`, converted to ggml) | https://huggingface.co/ggerganov/whisper.cpp | SHA-256 `c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d` | MIT | HF model card states "License: mit"; converted from OpenAI Whisper (MIT) |
| `qwen3:4b` | Ollama registry (`ollama pull qwen3:4b`) | tag `qwen3:4b` | Apache-2.0 | HF model card `Qwen/Qwen3-4B` states "License: apache-2.0" |

`scripts/download-models.sh` fetches the Whisper model directly from the upstream
Hugging Face repository and verifies the pinned SHA-256. `scripts/setup-ollama.sh`
pulls the Qwen model through Ollama. Neither artifact is stored in this
repository.

## Build / setup tools (used by the scripts, not distributed)

`git` (GPL-2.0), `cmake` (BSD-3-Clause), `g++`/`gcc` (GPL-3.0-or-later with the
GCC Runtime Library Exception), `curl` (curl license), `coreutils`/`sha256sum`
(GPL-3.0-or-later), `systemd`/`systemctl` (LGPL-2.1-or-later).

## Python

hyprwhispr uses **only the Python standard library** at runtime; it ships no
Python dependency. A build requires `setuptools` (MIT). Development/tests use
`pytest` (MIT). Python itself is under the PSF License 2.0.

## Assets in this repository

There are no images, fonts or icons copied from third parties. Diagrams are
plain text (Markdown/ASCII). The `examples/` configuration files are original
work and contain no personal data.

## Provenance of the code in this repository

The code under `src/hyprwhispr/`, the tests, scripts and documentation were
authored for this project **with AI assistance**. No third-party source file was
intentionally copied and no file carries a foreign copyright header, but
AI-generated code can resemble its training data and its copyright status is not
automatic. This is stated openly rather than asserting that the code is
untainted. If you adapt code from another project, record its origin and licence
here and in `docs/license-audit.md`.
