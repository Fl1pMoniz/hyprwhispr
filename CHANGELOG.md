# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/).

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
