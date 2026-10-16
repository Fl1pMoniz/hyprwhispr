# Third-Party Notices

hyprwhispr's own source code is licensed under the MIT License (see `LICENSE`).

The repository does **not** bundle any third-party source code, model weights,
binaries or fonts. The only things fetched are downloaded by the user at setup
time, from their upstream projects, into the user's data directory
(`~/.local/share/hyprwhispr` by default). This file records the provenance and
licences of those components so redistributors and users can review them.

## Runtime dependencies (installed by the user, not distributed here)

| Component | Used for | Upstream | Licence |
|---|---|---|---|
| **whisper.cpp** | local speech-to-text engine (built by `scripts/setup-whisper.sh`) | https://github.com/ggml-org/whisper.cpp | MIT |
| **ggml** (bundled inside whisper.cpp) | tensor library used by whisper.cpp | https://github.com/ggml-org/ggml | MIT |
| **whisper.cpp ggml model** (`ggml-small.en.bin`) | English speech recognition weights (downloaded by `scripts/download-models.sh`) | https://huggingface.co/ggerganov/whisper.cpp | MIT (see note below) |
| **Ollama** | local LLM server, HTTP API on `127.0.0.1:11434` | https://github.com/ollama/ollama | MIT |
| **Qwen3** model (`qwen3:4b`, pulled by the user via `ollama pull`) | general-purpose inference | https://huggingface.co/Qwen | Apache-2.0 |
| **PipeWire / `pw-record`** | microphone capture | https://pipewire.org | MIT |
| **Hyprland / `hyprctl`** | compositor and window control | https://github.com/hyprwm/Hyprland | BSD-3-Clause |
| **libnotify / `notify-send`** | desktop notifications | https://gitlab.gnome.org/GNOME/libnotify | MIT |
| **zenity** / **rofi** | confirmation dialogs | GNOME / rofi | LGPL-2.1 / MIT |
| **libglib / `gio`** | moving files to the trash | https://gitlab.gnome.org/GNOME/glib | LGPL-2.1 |

## Model weights: licence notes and uncertainties

Model licences are separate from the runtime that loads them. A permissively
licensed runtime (whisper.cpp, Ollama) does **not** automatically grant
redistribution rights over model weights.

- **whisper.cpp `ggml-*.bin` models** are converted from OpenAI's Whisper weights
  and distributed by the whisper.cpp project. OpenAI Whisper is released under the
  MIT License. Because the converted files are hosted by a third party, their exact
  licence metadata can change; they are downloaded directly from the upstream
  Hugging Face repository at setup time and are **not** redistributed by this
  project. `scripts/download-models.sh` verifies a pinned SHA-256 by default and
  documents the source URL.
- **Qwen3** weights are published under the Apache-2.0 License. They are pulled by
  the user through Ollama, from Ollama's own registry, and are not redistributed
  here.

Because hyprwhispr only fetches these files at the user's request and never ships
them, this project is not acting as a redistributor of the model weights. If you
fork this project and decide to ship models or a whisper.cpp checkout inside the
repository, review and reproduce the upstream licences yourself first.

## Assets in this repository

There are no images, fonts or icons copied from third parties. Any diagram is
plain text (Markdown / ASCII). The `examples/` configuration files are original
work and contain no personal data.

## Provenance of the code in this repository

The Python code under `src/hyprwhispr/` was written for this project. It contains
no copied third-party source. If a future contribution adapts code from another
project, the contributor must record its origin and licence here.
