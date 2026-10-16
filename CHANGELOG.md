# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Automatic multilingual speech recognition.** Default model is now the
  multilingual `ggml-small.bin` and `language` defaults to `null` (whisper's
  built-in auto-detection, `-l auto`). Speak Portuguese, English, Spanish and
  other languages without per-language configuration; the transcript and reply
  stay in the spoken language (transcription mode is used, never translation).
- `speech.resolve_language` / `speech.build_command` with a format check for
  explicit language codes (any short ISO-639 code is passed through to whisper).
- Benchmark extensions: multilingual fixtures (pt/es/de/it/ar/ja/zh), a separate
  transcription-latency mode (`--transcribe FILE.wav`), a multilingual-subset
  accuracy line, a script-based answer-language signal for non-Latin replies, a
  per-stage latency breakdown (total/LLM/tool/per-call), and optional word-error
  rate over local recordings (`--wer MANIFEST`).
- Optional `max_tokens` config (Ollama `num_predict`) to cap generated tokens per
  reply; `null` by default. Capping bounds worst-case latency but can hurt
  tool-selection accuracy at low values - measure with the benchmark first.
- Per-turn timing instrumentation (total, LLM, tool, per-call durations, and
  prompt/eval token counts) recorded in the audit log with no transcript content.

### Changed
- `scripts/download-models.sh` defaults to the multilingual model, downloads to a
  `.part` file, verifies the pinned SHA-256, and only then installs it; the
  English-only `ggml-small.en.bin` remains available via `WHISPER_MODEL_NAME`.
- `scripts/verify.sh` checks for the multilingual model and warns if only the
  English-only model is present.
- Ollama system prompt instructs the assistant to reply in the user's language.
- Tool-call JSON is only parsed from clear machine syntax (`<tool_call>` blocks, a
  fenced `json` block, or content that is itself a JSON object); a JSON object
  embedded in prose is no longer executed.

### Fixed
- Strip leaked `<tool_call>` markup and bare tool-call JSON envelopes from a reply
  so a model that echoes a tool call as text can no longer show raw JSON to the
  user; when nothing user-facing remains, make one bounded retry and then fall
  back to a short safe message.
- `scripts/benchmark.py` no longer leaves a patched model in the process after a
  fake-mode run (it now always restores `llm.ollama_chat`).

## [1.1.0] - 2026-10-16

Natural-language intelligence, reliable tool calling, context and speech-quality
overhaul.

### Added
- **Conversation context**: a small, bounded, expiring session (`session.py`) so
  follow-ups such as "now close it" resolve against the recent turn and the last
  referenced app/game. New `session` and `session clear` commands.
- **Ambiguity handling**: when several apps/games match with no clear winner,
  `open_app`/`close_app` ask instead of guessing; choices are remembered for the
  next turn. New `resolve <query>` command to inspect ranked candidates.
- **Runtime-compatibility fallback**: `ToolsUnsupported` triggers a strict
  constrained-JSON tool protocol for servers/models without native tool calling
  (`tool_mode` = `auto` | `native` | `json`).
- **Speech robustness**: silence and short-record gates (`min_record_ms`,
  `silence_threshold_db`), transcription cleanup, and automatic GPU→CPU
  fallback on CUDA errors.
- **Benchmark harness** (`scripts/benchmark.py`) over `tests/eval/requests.json`
  with tool-selection/argument accuracy, clarification and unsafe-action
  metrics, and latency percentiles.
- Config options: `request_timeout`, `max_tool_steps`, `tool_mode`,
  `model_aliases`, `whisper_timeout`, `min_record_ms`, `silence_threshold_db`,
  `keep_recordings`, `history_turns`, `session_ttl_minutes`,
  `app_ambiguity_margin`, `tool_timeout`, `log_transcripts`, `log_tool_args`.

### Changed
- Agent loop: bounded steps, duplicate tool-call suppression, per-call timings,
  forced plain-text answer when the budget is exhausted, and explicit errors for
  unknown tools / malformed arguments.
- App/game resolution: Unicode and punctuation normalization, filler-word
  filtering, ranked candidates, configured alias matching on tokens, and
  `ambiguous:` results.
- Privacy defaults: transcripts and tool arguments are no longer written to logs
  unless explicitly enabled.
- `recall` with no key lists everything remembered.
- Recording files are cleaned up after processing unless `keep_recordings` is set.

### Documentation and compliance
- Added `docs/license-audit.md`: an evidence-based license/provenance audit with
  verified upstream licenses, uncertainties and the AI-assisted-provenance caveat.
- Corrected `THIRD_PARTY_NOTICES.md`: **libnotify is LGPL-2.1** (was stated as
  MIT), completed the invoked-only tool inventory, and stated the AI-provenance
  caveat honestly instead of claiming the code is untainted.
- Added `scripts/audit.sh`, a dependency-free hygiene/dependency inventory.

### Tests
- Added session, speech, audio-probe, agent-loop and benchmark tests; suite grew
  from 40 to 82 tests.

## [1.0.0] - 2026-10-16

Initial release.

### Added
- Hold-to-talk voice input on Hyprland via `record-start` / `record-stop`
  bindings.
- Local English speech-to-text with whisper.cpp (CUDA or CPU).
- Local inference through Ollama (default `qwen3:4b`), text-only replies.
- Tool calling with typed JSON schemas for: opening/closing apps and Steam
  games, listing apps and games, web search, notes, remembered preferences,
  launching OpenCode, and confirmation-gated shell/install/delete actions.
- Dynamic application and Steam discovery from `.desktop` files and
  `appmanifest_*.acf` libraries.
- Confirmation gate (`zenity`/`rofi`) that fails closed, plus a local JSONL
  audit log.
- Microphone helpers (`list-mics`, `mictest`) and a terminal `listen` mode.
- Setup, verification and uninstall scripts; unit and security test suite.
