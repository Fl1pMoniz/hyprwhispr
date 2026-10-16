#!/usr/bin/env bash
# Build whisper.cpp locally (CUDA if available, otherwise CPU-only).
#
# Idempotent: does nothing if whisper-cli is already built. Everything is placed
# under the hyprwhispr data directory, so it does not touch system packages.
set -euo pipefail

DATA_DIR="${HYPRWHISPR_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/hyprwhispr}"
SRC_DIR="$DATA_DIR/whisper.cpp"
BUILD_DIR="$SRC_DIR/build"
CLI="$BUILD_DIR/bin/whisper-cli"

# Pinned upstream revision for reproducible builds. Override with WHISPER_CPP_COMMIT.
COMMIT="${WHISPER_CPP_COMMIT:-0c7be696371069e0baa2515ed7aa08d5a5473aa6}"
REPO="${WHISPER_CPP_REPO:-https://github.com/ggml-org/whisper.cpp}"

if [ -x "$CLI" ]; then
  echo "whisper.cpp already built: $CLI"
  exit 0
fi

for tool in git cmake; do
  command -v "$tool" >/dev/null 2>&1 || { echo "error: '$tool' is required" >&2; exit 1; }
done
if ! command -v c++ >/dev/null 2>&1 && ! command -v g++ >/dev/null 2>&1; then
  echo "error: a C++ compiler (g++) is required" >&2
  exit 1
fi

mkdir -p "$DATA_DIR"
if [ ! -d "$SRC_DIR/.git" ]; then
  echo "Cloning whisper.cpp into $SRC_DIR"
  git clone "$REPO" "$SRC_DIR"
fi
echo "Checking out $COMMIT"
git -C "$SRC_DIR" fetch --depth 1 origin "$COMMIT"
git -C "$SRC_DIR" checkout --detach "$COMMIT"

CMAKE_FLAGS=(-DCMAKE_BUILD_TYPE=Release)
if command -v nvcc >/dev/null 2>&1; then
  echo "CUDA toolkit found - building with GPU support"
  CMAKE_FLAGS+=(-DGGML_CUDA=1)
else
  echo "No CUDA toolkit found - building CPU-only (set whisper_gpu=false in config)"
fi

cmake -S "$SRC_DIR" -B "$BUILD_DIR" "${CMAKE_FLAGS[@]}"
cmake --build "$BUILD_DIR" -j"$(nproc)"

echo
echo "Built: $CLI"
echo "hyprwhispr will use it automatically."
