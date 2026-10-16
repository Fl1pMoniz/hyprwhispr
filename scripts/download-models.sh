#!/usr/bin/env bash
# Download the English Whisper ggml model used for speech recognition.
#
# The model is fetched from the upstream whisper.cpp Hugging Face repository and
# verified against a pinned SHA-256. Set HYPRWHISPR_SKIP_CHECKSUM=1 to bypass the
# check if upstream re-publishes the file.
set -euo pipefail

DATA_DIR="${HYPRWHISPR_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/hyprwhispr}"
MODEL_DIR="$DATA_DIR/models"
MODEL_FILE="$MODEL_DIR/ggml-small.en.bin"

MODEL_URL="${WHISPER_MODEL_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin}"
EXPECTED_SHA256="${WHISPER_MODEL_SHA256:-c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d}"

command -v curl >/dev/null 2>&1 || { echo "error: 'curl' is required" >&2; exit 1; }
mkdir -p "$MODEL_DIR"

sha_of() { sha256sum "$1" | awk '{print $1}'; }

if [ -f "$MODEL_FILE" ]; then
  if [ "${HYPRWHISPR_SKIP_CHECKSUM:-0}" = "1" ] || [ "$(sha_of "$MODEL_FILE")" = "$EXPECTED_SHA256" ]; then
    echo "model already present and verified: $MODEL_FILE"
    exit 0
  fi
  echo "existing model failed checksum; re-downloading"
  rm -f "$MODEL_FILE"
fi

echo "Downloading $MODEL_URL"
echo "(source: ggml-org/whisper.cpp on Hugging Face; OpenAI Whisper weights, MIT)"
curl -fL --retry 3 -o "$MODEL_FILE.part" "$MODEL_URL"
mv "$MODEL_FILE.part" "$MODEL_FILE"

if [ "${HYPRWHISPR_SKIP_CHECKSUM:-0}" != "1" ]; then
  actual="$(sha_of "$MODEL_FILE")"
  if [ "$actual" != "$EXPECTED_SHA256" ]; then
    echo "warning: SHA-256 mismatch for $MODEL_FILE" >&2
    echo "  expected: $EXPECTED_SHA256" >&2
    echo "  actual:   $actual" >&2
    echo "  set HYPRWHISPR_SKIP_CHECKSUM=1 to accept, or update the expected value." >&2
    exit 1
  fi
  echo "checksum verified"
fi

echo "Saved: $MODEL_FILE"
