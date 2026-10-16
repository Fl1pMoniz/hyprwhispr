#!/usr/bin/env bash
# Pull the language model used for inference, if Ollama is installed.
#
# This does NOT install Ollama and does NOT run any remote install script.
# See https://ollama.com/download/linux for the official installer.
set -euo pipefail

MODEL="${HYPRWHISPR_MODEL:-qwen3:4b}"

if ! command -v ollama >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Ollama is not installed.

Install it from the official source for your distribution, for example:
  https://ollama.com/download/linux

Then start it (a user service is common):
  systemctl --user enable --now ollama
and re-run this script.
EOF
  exit 1
fi

echo "Ollama found: $(command -v ollama)"
if ! ollama list 2>/dev/null | grep -q "^${MODEL%%:*}"; then
  echo "Pulling model: $MODEL"
  ollama pull "$MODEL"
else
  echo "Model already present: $MODEL"
fi
echo "Done."
