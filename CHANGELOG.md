# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/).

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
