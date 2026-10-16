#!/usr/bin/env bash
# Check that the local dependencies hyprwhispr needs are present.
# Read-only: it inspects the system and the *effective* configuration and checks
# that the configured programs exist and are executable. It never runs them.
set -uo pipefail

DATA_DIR="${HYPRWHISPR_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/hyprwhispr}"
CONFIG_FILE="${HYPRWHISPR_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/hyprwhispr/config.json}"
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

# Read one key from the effective config; fall back to the default when absent.
# Uses python3 (a required dependency) to parse JSON; never executes user input.
cfg_val() { # key default
  local key="$1" default="$2"
  if [ -f "$CONFIG_FILE" ] && command -v python3 >/dev/null 2>&1; then
    python3 - "$CONFIG_FILE" "$key" "$default" 2>/dev/null <<'PY' || printf '%s' "$default"
import json, sys
try:
    value = json.load(open(sys.argv[1])).get(sys.argv[2], sys.argv[3])
except Exception:
    value = sys.argv[3]
print("" if value is None else value)
PY
  else
    printf '%s' "$default"
  fi
}

echo "hyprwhispr dependency check"
echo "config:   $CONFIG_FILE"
echo "data dir: $DATA_DIR"
echo
echo "Required tools:"
check python3 python3
check notify-send notify-send
check ollama ollama
if command -v pw-record >/dev/null 2>&1; then
  printf "  [ok]   %-14s %s\n" "pw-record" "$(command -v pw-record)"; ok=$((ok+1))
elif command -v parecord >/dev/null 2>&1; then
  printf "  [ok]   %-14s %s\n" "parecord" "$(command -v parecord)"; ok=$((ok+1))
else
  printf "  [MISS] %-14s (required; install pipewire-utils)\n" "recorder"; fail=$((fail+1))
fi

echo "Optional tools:"
optional ffmpeg ffmpeg
optional gtk-launch gtk-launch
optional hyprctl hyprctl
optional wl-copy wl-copy
optional zenity zenity
optional rofi rofi

echo
echo "Speech-to-text (whisper.cpp):"
wb="$(cfg_val whisper_bin "$DATA_DIR/whisper.cpp/build/bin/whisper-cli")"
wm="$(cfg_val whisper_model "$DATA_DIR/models/ggml-small.bin")"
# The executable may be a configured path, or available on PATH under its name.
if [ -n "$wb" ] && [ -x "$wb" ]; then
  echo "  [ok]   whisper binary: $wb"
elif command -v whisper-cli >/dev/null 2>&1; then
  echo "  [ok]   whisper-cli on PATH: $(command -v whisper-cli)"
else
  echo "  [MISS] whisper binary not executable: $wb"
  echo "         (configured by 'whisper_bin'); run scripts/setup-whisper.sh or fix the path"
  fail=$((fail+1))
fi
if [ -n "$wm" ] && [ -f "$wm" ]; then
  case "$(basename "$wm")" in
    ggml-small.en.bin)
      echo "  [warn] English-only model: $wm (no automatic language detection)"
      warn=$((warn+1)) ;;
    *)
      echo "  [ok]   speech model: $wm" ;;
  esac
elif [ -f "$DATA_DIR/models/ggml-small.bin" ]; then
  echo "  [warn] configured model missing ($wm); multilingual model present at $DATA_DIR/models/ggml-small.bin"
  warn=$((warn+1))
else
  echo "  [MISS] speech model not found: $wm (run scripts/download-models.sh)"
  fail=$((fail+1))
fi

echo
echo "Browser (used by web_search; discovered, not assumed):"
bbin="$(cfg_val browser_bin "")"
browser=""
if [ -n "$bbin" ]; then
  if [ -x "$bbin" ] || command -v "$bbin" >/dev/null 2>&1; then browser="$bbin"; fi
else
  for b in firefox firefox-esr librewolf chromium chromium-browser brave-browser \
           google-chrome-stable google-chrome microsoft-edge-stable vivaldi-stable; do
    if command -v "$b" >/dev/null 2>&1; then browser="$(command -v "$b")"; break; fi
  done
  if [ -z "$browser" ] && command -v xdg-open >/dev/null 2>&1; then
    browser="$(command -v xdg-open) (generic opener)"
  fi
fi
if [ -n "$browser" ]; then
  echo "  [ok]   $browser"
else
  echo "  [warn] no browser found; install one or set \"browser_bin\" (web_search needs it)"
  warn=$((warn+1))
fi

echo "Terminal (used by OpenCode and terminal apps):"
tbin="$(cfg_val terminal_bin kitty)"
terminal=""
if [ -n "$tbin" ] && command -v "$tbin" >/dev/null 2>&1; then
  terminal="$tbin"
else
  for t in kitty foot alacritty wezterm konsole gnome-terminal xfce4-terminal xterm; do
    if command -v "$t" >/dev/null 2>&1; then terminal="$(command -v "$t")"; break; fi
  done
fi
if [ -n "$terminal" ]; then
  echo "  [ok]   $terminal"
else
  echo "  [warn] no terminal emulator found; set \"terminal_bin\" for OpenCode/terminal apps"
  warn=$((warn+1))
fi

echo
echo "Ollama:"
model="$(cfg_val model "$MODEL")"
url="$(cfg_val ollama_url "$OLLAMA_URL")"
if command -v curl >/dev/null 2>&1 && curl -fsS "$url/api/version" >/dev/null 2>&1; then
  echo "  [ok]   server reachable at $url"
  if command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | grep -q "^${model%%:*}"; then
    echo "  [ok]   model $model present"
  else
    echo "  [warn] model $model not found (run: ollama pull $model)"; warn=$((warn+1))
  fi
else
  echo "  [MISS] Ollama not reachable at $url (run: ollama serve)"; fail=$((fail+1))
fi

echo
echo "Summary: $ok ok, $warn warnings, $fail missing"
[ "$fail" -eq 0 ]
