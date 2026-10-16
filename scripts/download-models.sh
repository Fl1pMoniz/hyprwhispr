#!/usr/bin/env bash
# Download a Whisper ggml model for local speech recognition.
#
# Default: the MULTILINGUAL ggml-small.bin, which supports automatic language
# detection. The English-only ggml-small.en.bin is kept as a known alternative.
#
# The file is fetched from the upstream whisper.cpp Hugging Face repository,
# downloaded to a temporary .part file, verified against a pinned SHA-256, and
# only then installed at its final path.
#
# Overrides:
#   WHISPER_MODEL_NAME        model file name        (default: ggml-small.bin)
#   WHISPER_MODEL_URL         full download URL
#   WHISPER_MODEL_SHA256      expected SHA-256
#   HYPRWHISPR_SKIP_CHECKSUM  set to 1 to skip verification
set -euo pipefail

DATA_DIR="${HYPRWHISPR_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/hyprwhispr}"
MODEL_NAME="${WHISPER_MODEL_NAME:-ggml-small.bin}"
MODEL_DIR="$DATA_DIR/models"
MODEL_FILE="$MODEL_DIR/$MODEL_NAME"

BASE_URL="${WHISPER_MODEL_BASE_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main}"
MODEL_URL="${WHISPER_MODEL_URL:-$BASE_URL/$MODEL_NAME}"

# Pinned SHA-256 for the models we ship by name; anything else must be verified
# by setting WHISPER_MODEL_SHA256, otherwise verification is skipped with a warning.
case "$MODEL_NAME" in
  # multilingual (default) - supports auto language detection
  ggml-small.bin)    PINNED_SHA256="1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b" ;;
  # English-only alternative
  ggml-small.en.bin) PINNED_SHA256="c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d" ;;
  *)                 PINNED_SHA256="" ;;
esac
EXPECTED_SHA256="${WHISPER_MODEL_SHA256:-$PINNED_SHA256}"

command -v curl >/dev/null 2>&1 || { echo "error: 'curl' is required" >&2; exit 1; }
mkdir -p "$MODEL_DIR"

sha_of() { sha256sum "$1" | awk '{print $1}'; }

# Already installed (and, when a checksum is known, intact)?
if [ -f "$MODEL_FILE" ]; then
  if [ "${HYPRWHISPR_SKIP_CHECKSUM:-0}" = "1" ] || [ -z "$EXPECTED_SHA256" ] \
     || [ "$(sha_of "$MODEL_FILE")" = "$EXPECTED_SHA256" ]; then
    echo "model already present: $MODEL_FILE"
    exit 0
  fi
  echo "existing model failed checksum; re-downloading"
  rm -f "$MODEL_FILE"
fi

echo "Downloading $MODEL_URL"
echo "(source: ggml-org/whisper.cpp on Hugging Face; OpenAI Whisper weights, MIT)"
curl -fL --retry 3 -o "$MODEL_FILE.part" "$MODEL_URL"

# Verify the downloaded bytes BEFORE moving them into place.
if [ "${HYPRWHISPR_SKIP_CHECKSUM:-0}" = "1" ]; then
  echo "checksum verification skipped (HYPRWHISPR_SKIP_CHECKSUM=1)"
elif [ -z "$EXPECTED_SHA256" ]; then
  echo "warning: no pinned checksum for '$MODEL_NAME'; skipping verification" >&2
  echo "         set WHISPER_MODEL_SHA256=<sha256> to verify it." >&2
else
  actual="$(sha_of "$MODEL_FILE.part")"
  if [ "$actual" != "$EXPECTED_SHA256" ]; then
    rm -f "$MODEL_FILE.part"
    echo "error: SHA-256 mismatch for $MODEL_NAME (file removed, nothing installed)" >&2
    echo "  expected: $EXPECTED_SHA256" >&2
    echo "  actual:   $actual" >&2
    echo "  set HYPRWHISPR_SKIP_CHECKSUM=1 only if you trust the source." >&2
    exit 1
  fi
  echo "checksum verified"
fi

mv "$MODEL_FILE.part" "$MODEL_FILE"
echo "Saved: $MODEL_FILE"
