# License and Provenance Audit

**Scope:** the `hyprwhispr` repository (`Fl1pMoniz/hyprwhispr`).
**Audit date:** 2026-10-16.
**Revision audited:** working tree based on commit `c5c648c` (two commits total in
history: `eca72a9` "Initial release", `c5c648c` console-entry fix). The audit
covers tracked files plus the uncommitted 1.1.0 changes in the working tree.

This audit records evidence and uncertainty. It is **not legal advice** and does
not certify compliance; where evidence was unavailable the item is marked
unverified.

---

## 1. What was examined

- All tracked files (`git ls-files`) and untracked working-tree files.
- Full Git history and object database (for accidentally committed artifacts,
  secrets or large blobs).
- `LICENSE`, `pyproject.toml`, `THIRD_PARTY_NOTICES.md`, `README.md`,
  `.gitignore`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/**`, `examples/**`.
- Every external command the code and scripts invoke (`grep` over
  `src/hyprwhispr/**` and `scripts/**`).
- The setup scripts' download/build steps (`scripts/setup-whisper.sh`,
  `scripts/download-models.sh`, `scripts/setup-ollama.sh`).
- Upstream license files fetched directly (see §3) and, for whisper.cpp, the
  local checkout at `~/.local/share/local-assistant/whisper.cpp`.

## 2. Repository contents and history

- **Tracked files:** 43 (Python package, tests, docs, shell scripts, examples,
  metadata). No vendored third-party source tree is tracked.
- **Largest objects in history:** none above 100 KB. `git count-objects` reports
  56 loose objects, 0 packed — no model weights, binaries, archives or generated
  artifacts were ever committed.
- **Secrets/personal data in history:** none found. The only identity present is
  the Git author `ganzaman <62731476+Fl1pMoniz@users.noreply.github.com>`, which
  is the intended GitHub noreply identity.
- `.gitignore` excludes `*.bin`, `*.gguf`, `models/`, `build/`, `dist/`,
  `.venv/`, `__pycache__/`, `*.egg-info/`, `cache/`, `logs/`, `notes/`, `*.wav`
  and a vendored `whisper.cpp/`. This prevents committing model weights, build
  outputs and personal runtime data.

**Finding:** the shipped repository contains only original project text/code and
documentation. No historical remediation is required; there is nothing to remove
from history.

## 3. Confirmed license findings (with evidence)

Evidence was read from the upstream license file or the authoritative model card.

### Project's own code

- `LICENSE` is the verbatim MIT License, copyright `2026 hyprwhispr contributors`.
- `pyproject.toml` declares `license = { text = "MIT" }` and the classifier
  `License :: OSI Approved :: MIT License` — consistent with `LICENSE`.
- **Provenance caveat:** the code was authored **with AI assistance**. No
  third-party source file was intentionally copied, and no file carries a
  foreign copyright header, but AI-generated code can resemble its training data
  and its copyright status is not automatically clear. See §5.

### Software invoked or built (not redistributed)

| Component | Relationship | Pinned | License | Evidence |
|---|---|---|---|---|
| whisper.cpp | downloaded + compiled by user | commit `0c7be696371069e0baa2515ed7aa08d5a5473aa6` | MIT | local `LICENSE`: "Copyright (c) 2023-2026 The ggml authors" |
| ggml (bundled in whisper.cpp) | built with whisper.cpp | same commit | MIT | covered by whisper.cpp `LICENSE` (same authors); no separate `ggml/LICENSE` in this checkout |
| Ollama | invoked (`ollama`, HTTP API) | user-installed | MIT | upstream `LICENSE` ("Copyright (c) Ollama") |
| PipeWire (`pw-record`, `wpctl`) | invoked | system | MIT | upstream `LICENSE` ("All PipeWire source files are licensed under the MIT License"; some plugins LGPL/GPL) |
| Hyprland (`hyprctl`) | invoked | system | BSD-3-Clause | upstream `LICENSE` ("Copyright (c) 2022-2026, vaxerski") |
| rofi | invoked (dialog) | system | MIT/X11 | upstream `COPYING` (Qball Cow, Sean Pringle) |
| libnotify (`notify-send`) | invoked | system | **LGPL-2.1** | GitHub repo license badge + `COPYING` (LGPL-2.1) |
| GLib (`gio`) | invoked | system | LGPL-2.1-or-later | upstream `COPYING` → `LICENSES/LGPL-2.1-or-later.txt` |

### Downloaded model weights (not redistributed)

| Artifact | Source | Pinned | License | Evidence |
|---|---|---|---|---|
| `ggml-small.bin` (default, multilingual) and `ggml-small.en.bin` (English-only) | `huggingface.co/ggerganov/whisper.cpp` | SHA-256 pinned in `scripts/download-models.sh` | MIT | HF model card: "License: mit"; converted from OpenAI Whisper (MIT); both artifacts live in the same MIT-licensed repository |
| `qwen3:4b` | Ollama registry (pulled by user) | tag `qwen3:4b` | Apache-2.0 | HF model card `Qwen/Qwen3-4B`: "License: apache-2.0" |

The project downloads these at the user's request and does not redistribute
them, so it is not themselves acting as a redistributor of the weights.

## 4. Potential attribution / redistribution problems

1. **Corrected: libnotify is LGPL-2.1, not MIT.** `THIRD_PARTY_NOTICES.md`
   previously stated MIT. Fixed in this change.
2. **Missing components** — `ffmpeg`, `gtk-launch` (GTK), `wl-copy`
   (wl-clipboard), `kitty`, `xdg-open`, `pgrep`/`pkill` (procps) and the build
   tools (`git`, `cmake`, `g++`, `curl`, `coreutils`) were not inventoried. They
   are only *invoked*, not linked or bundled, so no redistribution obligation
   arises from this repository; they are now listed for completeness.
3. **No SPDX headers in source files.** Not required for MIT, but it would make
   provenance explicit. Low priority.
4. **`pyproject.toml` uses the legacy `license = { text = "MIT" }`** rather than
   the PEP 639 SPDX expression plus `license-files`. Both are valid today; the
   modern form is clearer but may require newer setuptools. Left unchanged to
   avoid breaking the declared `setuptools>=64` build.
5. **Model vs. software licensing is correctly separated** in the notices; the
   fix keeps that separation and states that a permissive runtime does not
   license its weights.

## 5. Unverified claims and why

- **Authorship / provenance of the source.** The code was produced with AI
  assistance in this project. It is not possible to prove that no snippet
  resembles training data. Treated as unverified; the notices now say so plainly
  rather than claiming "no copied third-party source".
- **zenity** license (reported LGPL-2.1) was not independently fetched
  (GNOME GitLab is bot-protected). Listed as LGPL-2.1 with a "verify" note.
- **ffmpeg** license depends on how the distro built it (LGPL-2.1-or-later, or
  GPL if GPL components are enabled). Not verified for this specific Nobara
  build; not redistributed either way.
- **GTK (`gtk-launch`)**, **wl-clipboard**, **procps**, **xdg-utils**, **kitty**,
  **curl**, **cmake**, **git**, **g++**, **coreutils** licenses are cited from
  their well-known upstream projects but were not individually re-fetched in this
  audit.
- **`ggml`** has no standalone `LICENSE` file in the pinned whisper.cpp checkout;
  its MIT status is inferred from the whisper.cpp `LICENSE`, which names "The
  ggml authors". This is strong but indirect evidence.

## 6. Recommended actions (prioritised)

1. **(Done) Fix the libnotify license** in `THIRD_PARTY_NOTICES.md` (LGPL-2.1).
2. **(Done) Complete the inventory** with the invoked-only tools and separate
   software from model-weight licensing.
3. **(Done) State the AI-assisted provenance** honestly in the notices and here.
4. **(Done) Add `scripts/audit.sh`**, a lightweight, dependency-free hygiene
   check (tracked binaries/weights/secrets/large files, dependency list).
   Document its limits: it cannot prove provenance or grant legal clearance.
5. **Optional:** add SPDX headers to source files, and migrate `pyproject.toml`
   to the PEP 639 license expression once a newer setuptools is acceptable.
6. **If you ever bundle** whisper.cpp source, `ggml-*.bin` weights, or Ollama
   blobs inside the repository: reproduce the upstream `LICENSE` texts and
   re-run this audit first. The current design deliberately avoids bundling.

## 7. Remaining questions for human review

- Do you want the copyright holder in `LICENSE` to remain the collective
  "hyprwhispr contributors", or be your name/handle?
- Confirm you are comfortable distributing AI-assisted code under MIT given the
  provenance caveat in §5.
- If you plan a packaged/redistributed build (e.g. an RPM/Flatpak that ships
  whisper.cpp or model weights), a fuller review of the LGPL/BSD/GPL components
  above is warranted before publishing.

---

### Automated-check limitations

`scripts/audit.sh` performs deterministic checks only: which files are tracked,
whether any look like binaries/weights/secrets, and a list of declared
dependencies. It cannot detect copied code, cannot read model cards, and does not
establish legal compliance. Its output is a starting point for the human
reviewer, not a clearance.
