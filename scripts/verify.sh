#!/usr/bin/env bash
# Check that the local dependencies hyprwhispr needs are present.
# Read-only: it inspects the system and prints a report.
set -uo pipefail

DATA_DIR="${HYPRWHISPR_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/hyprwhispr}"
OLLAMA_URL="${HYPRWHISPR_OLLAMA_URL:-http://127.0.0.1:11434}"
MODEL="${HYPRWHISPR_MODEL:-qwen3:4b}"

ok=0; fail=0; warn=0
check() { # name, command
  if command -v "$2" >/dev/null 2>&1; then printf "  [ok]   %-14s %s\n" "$1" "$(command -v "$2")"; ok=$((ok+1));
  else printf "  [MISS] %-14s (required)\n" "$1"; fail=$((fail+1)); fi
}
optional() { # name, command
  if command -v "$2" >/dev/null 2>&1; then printf "  [ok]   %-14s %s\n" "$1" "$(command -v "$2")"; ok=$((ok+1));
  else printf "  [warn] %-14s not found (optional)\n" "$1"; warn=$((warn+1)); fi
}

echo "hyprwhispr dependency check"
echo "data dir: $DATA_DIR"
echo
echo "Required tools:"
check python3 python3
check pw-record pw-record
check notify-send notify-send
check ollama ollama

echo "Optional tools:"
optional ffmpeg ffmpeg
optional gtk-launch gtk-launch
optional hyprctl hyprctl
optional wl-copy wl-copy
optional zenity zenity
optional rofi rofi

echo
echo "Speech model:"
if [ -f "$DATA_DIR/models/ggml-small.en.bin" ]; then
  echo "  [ok]   ggml-small.en.bin"
else
  echo "  [MISS] $DATA_DIR/models/ggml-small.en.bin (run scripts/download-models.sh)"; fail=$((fail+1))
fi
echo "Whisper binary:"
if [ -x "$DATA_DIR/whisper.cpp/build/bin/whisper-cli" ]; then
  echo "  [ok]   whisper-cli"
else
  echo "  [MISS] $DATA_DIR/whisper.cpp/build/bin/whisper-cli (run scripts/setup-whisper.sh)"; fail=$((fail+1))
fi

echo
echo "Ollama:"
if command -v curl >/dev/null 2>&1 && curl -fsS "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
  echo "  [ok]   server reachable at $OLLAMA_URL"
  if command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | grep -q "^${MODEL%%:*}"; then
    echo "  [ok]   model $MODEL present"
  else
    echo "  [warn] model $MODEL not found (run: ollama pull $MODEL)"; warn=$((warn+1))
  fi
else
  echo "  [MISS] Ollama not reachable at $OLLAMA_URL (run: ollama serve)"; fail=$((fail+1))
fi

echo
echo "Summary: $ok ok, $warn warnings, $fail missing"
[ "$fail" -eq 0 ]
