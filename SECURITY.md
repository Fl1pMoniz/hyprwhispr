# Security Policy

## Scope

hyprwhispr runs locally with your user's privileges and controls applications,
windows and a microphone on your machine. Security-relevant areas include the
confirmation gates, tool argument validation, subprocess invocation, the web
search URL, and the local HTTP calls to Ollama.

## Design guarantees

- Speech recognition and language inference run locally (whisper.cpp and a
  loopback Ollama server). No cloud AI is used.
- The only network feature is an explicit web search that opens your browser.
- State-changing tools (`run_shell`, `install_package`, `delete_path`) always
  prompt for confirmation and deny by default when no answer is given.
- The model selects tools from typed schemas; it cannot inject raw shell text
  through the transcript except via the confirmation-gated `run_shell` tool.

## Reporting a vulnerability

Please do not open a public issue for security problems. Instead, contact the
maintainer privately (for example via the email on the GitHub profile) or use
GitHub's private vulnerability reporting on the repository. Include:

- a description of the issue and its impact,
- steps to reproduce,
- affected version/commit,
- any suggested fix.

We will acknowledge the report and work on a fix before public disclosure.

## Known limitations

- `run_shell` executes an arbitrary command once you approve it. Treat the
  transcript (and therefore the microphone) as trusted input for that tool.
- The assistant inherits your user's access; it does not sandbox launched
  applications.
