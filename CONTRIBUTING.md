# Contributing

Thanks for considering a contribution. hyprwhispr aims to stay small, readable
and honest.

## Ground rules

- Keep the runtime dependency-free (Python standard library only).
- Prefer clarity over cleverness. Small functions, descriptive names, a short
  docstring when the intent is not obvious.
- **Do not add cloud AI or remote speech services.** Inference and speech
  recognition must stay local. Network access is allowed only for an explicit,
  user-requested web search.
- Do not introduce arbitrary shell execution that is not behind the confirmation
  gate.
- Do not commit personal data, model weights, logs, recordings or secrets.

## Development setup

```bash
git clone https://github.com/<you>/hyprwhispr.git
cd hyprwhispr
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest
pytest -q
```

Tests use an isolated temporary data directory and mocks; they never touch a
real desktop, microphone or GPU.

## Adding a tool

1. Implement the tool in the relevant module (see `docs/tools.md`).
2. Register it in `TOOL_IMPL` and `TOOLS_SCHEMA` in `src/hyprwhispr/tools.py`.
3. If it changes state, call `permissions.confirm(...)` first and log the
   outcome with `notify.log_event`.
4. Add unit tests, including a denial path for anything gated.

## Pull requests

- Keep the change focused; one topic per PR.
- Run `pytest` and `scripts/verify.sh`.
- Describe what you tested and what you could not test (hardware, compositor,
  GPU, audio). Never claim a test passed if it did not run.
- Update the docs and `CHANGELOG.md` when behaviour changes.

## Code style

- 4-space indentation, ~100 column soft limit.
- Type hints on function signatures.
- No new third-party packages.
