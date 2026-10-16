#!/usr/bin/env bash
# hyprwhispr installer for Fedora / Nobara / Fedora-derived systems with Hyprland.
#
# Guided, idempotent, and reversible: it checks the environment, installs only
# what is missing (system packages via dnf, the app via pipx or a venv, the
# Ollama model, whisper.cpp and the Whisper model), never overwrites your config,
# and never edits your Hyprland configuration automatically.
#
# Run it from a clone:   ./scripts/install.sh
# Options:               --help --check --dry-run --yes --no-model-download
#
# Testability: set HYPRWHISPR_INSTALL_LIB=1 to source the file and call its
# functions without running main().

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

OS_RELEASE_FILE="${HYPRWHISPR_OS_RELEASE:-/etc/os-release}"
DATA_DIR="${HYPRWHISPR_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/hyprwhispr}"
CONFIG_DIR="${HYPRWHISPR_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/hyprwhispr}"
CONFIG_FILE="${HYPRWHISPR_CONFIG:-$CONFIG_DIR/config.json}"
RUNTIME_DIR="${HYPRWHISPR_RUNTIME:-${XDG_RUNTIME_DIR:-/tmp}/hyprwhispr}"
HYPR_DIR="${HYPR_CONF_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/hypr}"
OLLAMA_URL="${HYPRWHISPR_OLLAMA_URL:-http://127.0.0.1:11434}"

DEFAULT_MODEL="qwen3:4b"
WHISPER_DEFAULT_NAME="ggml-small.bin"
WHISPER_SMALL_SHA="1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"
WHISPER_SMALL_EN_SHA="c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"

DRY_RUN=0
ASSUME_YES=0
NO_MODEL=0
CHECK_ONLY=0

PASS=0
WARN=0
FAIL=0

# ---------------------------------------------------------------------------
# output helpers
# ---------------------------------------------------------------------------
say()  { printf '%s\n' "$*"; }
info() { printf '     %s\n' "$*"; }
ok()   { printf '  [PASS] %s\n' "$*"; PASS=$((PASS + 1)); }
warn() { printf '  [WARN] %s\n' "$*"; WARN=$((WARN + 1)); }
bad()  { printf '  [FAIL] %s\n' "$*"; FAIL=$((FAIL + 1)); }
die()  { printf 'error: %s\n' "$*" >&2; exit 2; }

have() { command -v "$1" >/dev/null 2>&1; }

path_contains() { # dir
  case ":$PATH:" in *":$1:"*) return 0 ;; *) return 1 ;; esac
}

# Print a runnable hyprwhispr CLI path (on PATH, or in ~/.local/bin), else nothing.
# Running the CLI works even when ~/.local/bin is not on PATH.
cli_bin_path() {
  if have hyprwhispr && hyprwhispr version >/dev/null 2>&1; then
    command -v hyprwhispr; return 0
  fi
  if [ -x "$HOME/.local/bin/hyprwhispr" ] && "$HOME/.local/bin/hyprwhispr" version >/dev/null 2>&1; then
    printf '%s' "$HOME/.local/bin/hyprwhispr"; return 0
  fi
  return 1
}

usage() {
  cat <<EOF
hyprwhispr installer (Fedora / Nobara / Fedora-derived, Hyprland)

Usage: ./scripts/install.sh [options]

Options:
  -h, --help              Show this help and exit.
      --check             Read-only: report missing and satisfied requirements.
      --dry-run           Show what would be done without changing anything.
  -y, --yes               Assume "yes" to the supported prompts (non-interactive).
      --no-model-download Skip pulling the Ollama and Whisper models.

The installer reuses scripts/setup-ollama.sh, setup-whisper.sh and
download-models.sh, never overwrites ~/.config/hyprwhispr/config.json, and never
edits your Hyprland configuration (it prints the binding to add).
EOF
}

# ---------------------------------------------------------------------------
# OS / distro detection
# ---------------------------------------------------------------------------
release_val() { # file key
  local f="$1" key="$2" line
  [ -f "$f" ] || return 0
  line="$(grep -E "^${key}=" "$f" 2>/dev/null | head -n1)" || return 0
  line="${line#*=}"
  line="${line%$'\r'}"
  line="${line%\"}"; line="${line#\"}"
  printf '%s' "$line"
}

detect_distro() {
  local f="$OS_RELEASE_FILE"
  [ -f "$f" ] || { printf 'unsupported'; return 0; }
  local id id_like variant
  id="$(release_val "$f" ID)"
  id_like="$(release_val "$f" ID_LIKE)"
  variant="$(release_val "$f" VARIANT_ID)"

  # Atomic / image-based variants (do not use ordinary dnf by default).
  if [ -e /run/ostree-booted ] \
     || printf '%s %s %s' "$id" "$id_like" "$variant" \
        | grep -qiE 'ostree|atomic|silverblue|kinoite|sericea|onyx|bazzite|bluefin|aurora|coreos'; then
    printf 'fedora-atomic'; return 0
  fi
  case "$id" in
    nobara) printf 'nobara'; return 0 ;;
    fedora) printf 'fedora'; return 0 ;;
  esac
  if printf '%s' "$id_like" | grep -qiE '(^| )fedora( |$)'; then
    printf 'fedora-derived'; return 0
  fi
  printf 'unsupported'
}

# ---------------------------------------------------------------------------
# config / path helpers
# ---------------------------------------------------------------------------
cfg_value() { # key default
  local key="$1" default="$2"
  if [ -f "$CONFIG_FILE" ] && have python3; then
    python3 - "$CONFIG_FILE" "$key" "$default" 2>/dev/null <<'PY' || printf '%s' "$default"
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    value = data.get(sys.argv[2], sys.argv[3])
except Exception:
    value = sys.argv[3]
print("" if value is None else value)
PY
  else
    printf '%s' "$default"
  fi
}

configured_model() {
  local m; m="$(cfg_value model "$DEFAULT_MODEL")"
  [ -n "$m" ] || m="$DEFAULT_MODEL"
  printf '%s' "$m"
}

whisper_bin_path() {
  printf '%s' "$(cfg_value whisper_bin "$DATA_DIR/whisper.cpp/build/bin/whisper-cli")"
}

speech_model_path() {
  printf '%s' "$(cfg_value whisper_model "$DATA_DIR/models/$WHISPER_DEFAULT_NAME")"
}

config_valid() {
  [ -f "$CONFIG_FILE" ] || return 1
  have python3 || return 0
  python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$CONFIG_FILE" >/dev/null 2>&1
}

python_ok() {
  have python3 || return 1
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}

ollama_api_up() {
  have curl && curl -fsS "$OLLAMA_URL/api/version" >/dev/null 2>&1
}

ollama_has_model() { # model
  have ollama || return 1
  ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Fxq "$1"
}

verify_model_sha() { # path -> 0 if known-and-valid or unknown
  local f="$1" name sha
  name="$(basename "$f")"
  case "$name" in
    "$WHISPER_DEFAULT_NAME") sha="$WHISPER_SMALL_SHA" ;;
    ggml-small.en.bin)       sha="$WHISPER_SMALL_EN_SHA" ;;
    *) return 0 ;; # unknown model: cannot verify, do not block
  esac
  have sha256sum || return 0
  [ "$(sha256sum "$f" 2>/dev/null | awk '{print $1}')" = "$sha" ]
}

binding_present() {
  [ -d "$HYPR_DIR" ] || return 1
  grep -rIqs 'hyprwhispr record-start' "$HYPR_DIR" 2>/dev/null
}

# ---------------------------------------------------------------------------
# confirmation / action wrapper
# ---------------------------------------------------------------------------
confirm() { # prompt
  [ "$ASSUME_YES" = 1 ] && return 0
  # Only prompt when stdin is a terminal; otherwise this is non-interactive and
  # we decline (fail-closed) so an unattended run never blocks or mutates anything.
  if [ -t 0 ]; then
    printf '  %s [y/N] ' "$1"
    local reply=""; read -r reply || reply=""
    case "${reply:-}" in [yY]*) return 0 ;; *) return 1 ;; esac
  fi
  return 1
}

do_action() { # "description" cmd args...
  local desc="$1"; shift
  if [ "$DRY_RUN" = 1 ]; then info "[dry-run] would $desc"; return 0; fi
  if ! confirm "$desc - proceed?"; then warn "skipped: $desc"; return 1; fi
  info "running: $desc"
  "$@"
}

pkg_manager() {
  if have dnf; then printf 'dnf'; elif have dnf5; then printf 'dnf5'; else printf ''; fi
}

install_packages() { # pkg...
  [ "$#" -eq 0 ] && return 0
  local pm; pm="$(pkg_manager)"
  if [ -z "$pm" ]; then
    warn "no dnf/dnf5 found; install manually: $*"
    return 1
  fi
  if ! have sudo; then
    warn "sudo not found; install as root: $pm install $*"
    return 1
  fi
  do_action "install system packages ($pm): $*" sudo "$pm" install -y "$@"
}

# ---------------------------------------------------------------------------
# requirement assessment (shared by --check and the final verification)
# ---------------------------------------------------------------------------
assess_requirements() {
  PASS=0; WARN=0; FAIL=0

  say "Core:"
  if python_ok; then ok "python3 $(python3 --version 2>&1 | awk '{print $2}')"; \
  else bad "python3 >= 3.9 is required"; fi
  have pw-record && ok "pw-record (PipeWire capture)" \
    || { have parecord && warn "parecord found; set \"recorder\": \"parecord\"" \
         || bad "pw-record/parecord missing (audio capture; install pipewire-utils)"; }

  local wb wm model
  wb="$(whisper_bin_path)"; wm="$(speech_model_path)"; model="$(configured_model)"

  if [ -x "$wb" ]; then ok "whisper.cpp build: $wb"; \
  else warn "whisper.cpp not built yet: $wb (installer will build it)"; fi

  if [ -f "$wm" ]; then
    if verify_model_sha "$wm"; then ok "speech model verified: $(basename "$wm")"; \
    else bad "speech model checksum mismatch: $wm"; fi
  else
    if [ "$NO_MODEL" = 1 ]; then warn "speech model missing (skipped: --no-model-download)"
    else warn "speech model not downloaded yet: $wm (installer will download it)"; fi
  fi

  if have ollama; then ok "ollama CLI"; else bad "ollama not installed (https://ollama.com/download/linux)"; fi
  if ollama_api_up; then
    ok "Ollama API reachable at $OLLAMA_URL"
    if ollama_has_model "$model"; then ok "model '$model' present"
    else [ "$NO_MODEL" = 1 ] && warn "model '$model' missing (skipped: --no-model-download)" \
                             || warn "model '$model' not pulled yet"; fi
  else
    warn "Ollama API not reachable at $OLLAMA_URL (is it running?)"
  fi

  say "Push-to-talk:"
  if have hyprctl; then
    if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then ok "Hyprland session active"
    else warn "hyprctl present but not inside a Hyprland session (bindings apply after login)"; fi
  else warn "hyprctl missing (Hyprland not detected; install Hyprland to use push-to-talk)"; fi
  if binding_present; then ok "Hyprland binding already present in $HYPR_DIR"
  else warn "no Hyprland binding detected (installer can write a snippet)"; fi

  say "Optional:"
  have notify-send && ok "notify-send (libnotify)" || warn "notify-send missing (replies fall back to terminal)"
  if have zenity || have rofi; then ok "confirmation dialog (zenity/rofi)"; \
  else warn "no zenity/rofi: confirmations deny (fail-closed)"; fi
  have gtk-launch && ok "gtk-launch" || warn "gtk-launch missing (apps fall back to Exec parsing)"
  have ffmpeg && ok "ffmpeg (mictest levels)" || warn "ffmpeg missing (mictest level analysis unavailable)"
  have wl-copy && ok "wl-copy (clipboard)" || warn "wl-copy missing (prompt copy unavailable)"

  say "Application:"
  if cli_bin_path >/dev/null 2>&1; then
    ok "hyprwhispr CLI installed: $(cli_bin_path)"
    path_contains "$HOME/.local/bin" || warn "~/.local/bin is not on PATH"
  else warn "hyprwhispr CLI not installed yet"; fi
  if [ -f "$CONFIG_FILE" ]; then
    if config_valid; then ok "config valid: $CONFIG_FILE"; else bad "config is not valid JSON: $CONFIG_FILE"; fi
  else warn "config not created yet: $CONFIG_FILE"; fi
}

print_summary() {
  say ""
  say "Summary: $PASS passed, $WARN warnings, $FAIL failed"
}

# ---------------------------------------------------------------------------
# installation steps
# ---------------------------------------------------------------------------
install_build_and_audio_packages() {
  local core=()
  if [ ! -x "$(whisper_bin_path)" ]; then
    have git   || core+=(git)
    have cmake || core+=(cmake)
    have make  || core+=(make)
    { have g++ || have c++; } || core+=(gcc-c++)
  fi
  { have pw-record || have parecord; } || core+=(pipewire-utils)
  have notify-send || core+=(libnotify)
  have curl || core+=(curl)
  # The app is installed with pipx when available (virtualenv otherwise); pull it in.
  if ! have pipx && ! cli_bin_path >/dev/null 2>&1; then core+=(pipx); fi
  if [ "${#core[@]}" -gt 0 ]; then
    say ""
    say "Missing required system packages: ${core[*]}"
    install_packages "${core[@]}" || warn "some core packages could not be installed"
  fi
}

install_optional_packages() {
  local opt=()
  if ! have zenity && ! have rofi; then opt+=(zenity); fi
  have wl-copy || opt+=(wl-clipboard)
  have ffmpeg || opt+=(ffmpeg-free)
  if [ "${#opt[@]}" -gt 0 ]; then
    say ""
    say "Optional packages that improve the experience: ${opt[*]}"
    install_packages "${opt[@]}" || warn "optional packages skipped (you can install them later)"
  fi
}

install_python_app() {
  if cli_bin_path >/dev/null 2>&1; then
    ok "hyprwhispr CLI already installed ($(cli_bin_path))"
    path_contains "$HOME/.local/bin" || warn "~/.local/bin is not on PATH - add: export PATH=\"\$HOME/.local/bin:\$PATH\""
    return 0
  fi
  if [ "$DRY_RUN" = 1 ]; then info "[dry-run] would install the hyprwhispr Python app"; return 0; fi

  if have pipx; then
    if pipx list --short 2>/dev/null | grep -q '^hyprwhispr '; then
      info "hyprwhispr is already installed with pipx"
    else
      do_action "install hyprwhispr with pipx" pipx install "$ROOT_DIR" \
        || warn "pipx install did not complete; trying a virtual environment"
    fi
    # NOTE: intentionally not running `pipx ensurepath`, which would edit shell
    # startup files; we only report the PATH change instead.
  fi

  if cli_bin_path >/dev/null 2>&1; then
    ok "hyprwhispr CLI installed ($(cli_bin_path))"
    path_contains "$HOME/.local/bin" || warn "~/.local/bin is not on PATH - add: export PATH=\"\$HOME/.local/bin:\$PATH\""
    return 0
  fi

  # venv fallback (kept under the data dir, never in the repository)
  local venv="$DATA_DIR/venv" bindir="$HOME/.local/bin"
  do_action "create a virtualenv and install hyprwhispr" bash -c \
    "python3 -m venv '$venv' && '$venv/bin/pip' install --quiet '$ROOT_DIR'" \
    || { bad "could not install the hyprwhispr Python app"; return 1; }
  mkdir -p "$bindir"
  printf '#!/usr/bin/env bash\nexec "%s/bin/python" -m hyprwhispr "$@"\n' "$venv" > "$bindir/hyprwhispr"
  chmod +x "$bindir/hyprwhispr"
  if path_contains "$bindir"; then
    ok "hyprwhispr installed to $bindir (on PATH)"
  else
    warn "hyprwhispr installed to $bindir, which is not on PATH - add: export PATH=\"$bindir:\$PATH\""
  fi
}

install_ollama_model() {
  local model; model="$(configured_model)"
  if [ "$NO_MODEL" = 1 ]; then warn "model download skipped (--no-model-download)"; return 0; fi
  if ! have ollama; then
    bad "Ollama is not installed; model '$model' not pulled"
    info "Install Ollama from https://ollama.com/download/linux then run: ollama pull $model"
    return 1
  fi
  if ollama_has_model "$model"; then ok "model '$model' already present"; return 0; fi
  say ""
  say "Model '$model' is not installed (approx. 2.5 GB for qwen3:4b)."
  if ollama_api_up; then
    do_action "pull the Ollama model '$model'" env HYPRWHISPR_MODEL="$model" bash "$SCRIPT_DIR/setup-ollama.sh" \
      || warn "model pull did not complete; run: ollama pull $model"
  else
    warn "Ollama API not reachable; start it then run: ollama pull $model"
  fi
}

install_whisper() {
  local wb; wb="$(whisper_bin_path)"
  if [ -x "$wb" ]; then ok "whisper.cpp already built"; return 0; fi
  if [ "$DRY_RUN" = 1 ]; then info "[dry-run] would build whisper.cpp via scripts/setup-whisper.sh"; return 0; fi
  # only the default data-dir build is handled by the setup script
  if [ "$wb" != "$DATA_DIR/whisper.cpp/build/bin/whisper-cli" ]; then
    warn "configured whisper_bin ($wb) is missing and not the default path; build it manually"
    return 1
  fi
  do_action "build whisper.cpp (pinned revision, CUDA if available)" bash "$SCRIPT_DIR/setup-whisper.sh" \
    || { bad "whisper.cpp build failed - install git, cmake, make and gcc-c++, then re-run scripts/setup-whisper.sh"; return 1; }
}

install_speech_model() {
  local wm; wm="$(speech_model_path)"
  local base="$DATA_DIR/models"
  if [ -f "$wm" ]; then
    if verify_model_sha "$wm"; then ok "speech model verified: $(basename "$wm")"; return 0; fi
    warn "existing speech model failed its checksum: $wm"
  fi
  if [ "$NO_MODEL" = 1 ]; then warn "speech model download skipped (--no-model-download)"; return 0; fi
  if [ "$wm" != "$base/$WHISPER_DEFAULT_NAME" ]; then
    warn "no speech model at the configured path ($wm); set whisper_model or re-run scripts/download-models.sh"
    return 1
  fi
  say ""
  say "The multilingual Whisper model ($WHISPER_DEFAULT_NAME, approx. 466 MB) is missing."
  do_action "download and verify the Whisper speech model" bash "$SCRIPT_DIR/download-models.sh" \
    || { bad "speech model download failed"; return 1; }
  [ -f "$wm" ] && ok "speech model installed: $(basename "$wm")"
}

install_config() {
  if [ -f "$CONFIG_FILE" ]; then
    if config_valid; then ok "keeping existing config: $CONFIG_FILE"
    else warn "existing config is not valid JSON and was left untouched: $CONFIG_FILE"; fi
    return 0
  fi
  if [ "$DRY_RUN" = 1 ]; then info "[dry-run] would create $CONFIG_FILE from examples/config.example.json"; return 0; fi
  if confirm "create the default config at $CONFIG_FILE - proceed?"; then
    mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$RUNTIME_DIR"
    cp "$ROOT_DIR/examples/config.example.json" "$CONFIG_FILE"
    ok "created config: $CONFIG_FILE"
  else
    warn "config not created; copy examples/config.example.json to $CONFIG_FILE yourself"
  fi
}

install_binding() {
  if binding_present; then ok "Hyprland binding already present"; return 0; fi
  say ""
  say "Hyprland hold-to-talk binding (add to your Hyprland config):"
  info "hyprlang:   bind  = SUPER, V, exec, hyprwhispr record-start"
  info "            bindr = SUPER, V, exec, hyprwhispr record-stop"
  info "Lua/KoolDots: see examples/hyprland-keybinds.lua"
  if [ ! -d "$HYPR_DIR" ]; then warn "no Hyprland config dir at $HYPR_DIR; skipping snippet"; return 0; fi
  local snippet="$HYPR_DIR/hyprwhispr.conf"
  if [ -f "$snippet" ] && grep -q 'hyprwhispr record-start' "$snippet" 2>/dev/null; then
    ok "binding snippet already present: $snippet"; return 0
  fi
  if [ "$DRY_RUN" = 1 ]; then info "[dry-run] would write $snippet"; return 0; fi
  if confirm "write a Hyprland binding snippet to $snippet - proceed?"; then
    {
      echo "# hyprwhispr hold-to-talk binding (created by install.sh)"
      echo "bind  = SUPER, V, exec, hyprwhispr record-start"
      echo "bindr = SUPER, V, exec, hyprwhispr record-stop"
    } > "$snippet"
    ok "wrote $snippet"
    info "hyprlang users: add  source = $snippet  to hyprland.conf, then: hyprctl reload"
    info "Lua users: add the hl.bind() pair from examples/hyprland-keybinds.lua instead."
  else
    warn "binding snippet not written"
  fi
}

final_verify() {
  say ""
  say "Verifying the installation:"
  local wb wm model
  wb="$(whisper_bin_path)"; wm="$(speech_model_path)"; model="$(configured_model)"
  [ -x "$wb" ] && ok "whisper.cpp executable present" \
    || bad "whisper.cpp executable missing: $wb (run scripts/setup-whisper.sh)"
  if [ -f "$wm" ] && verify_model_sha "$wm"; then ok "speech model present and valid"; \
  elif [ -f "$wm" ]; then bad "speech model present but invalid"; \
  elif [ "$NO_MODEL" = 1 ]; then warn "speech model absent (skipped)"; \
  else bad "speech model missing"; fi
  if have ollama; then
    if ollama_api_up && ollama_has_model "$model"; then ok "Ollama serving model '$model'"; \
    elif ollama_api_up; then
      if [ "$NO_MODEL" = 1 ]; then warn "Ollama running; model '$model' skipped (--no-model-download)"
      else bad "Ollama running but model '$model' not pulled (run: ollama pull $model)"; fi
    else warn "Ollama installed but API not reachable (start it, then: ollama pull $model)"; fi
  else bad "Ollama not installed"; fi
  if cli_bin_path >/dev/null 2>&1; then ok "hyprwhispr CLI works"; \
  else bad "hyprwhispr CLI not runnable"; fi
  [ -f "$CONFIG_FILE" ] && [ "$(config_valid && echo ok)" = ok ] && ok "config present and valid" \
    || warn "config not present/valid: $CONFIG_FILE"
  if have hyprctl; then
    if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then ok "Hyprland session active"; \
    else warn "not in a Hyprland session: test push-to-talk after login"; fi
  fi
  say ""
  say "Manual test (in a terminal):  hyprwhispr listen 6"
  say "Push-to-talk: hold SUPER+V, speak, release, after adding the binding."
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
main() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -h|--help) usage; return 0 ;;
      --check) CHECK_ONLY=1 ;;
      --dry-run) DRY_RUN=1 ;;
      -y|--yes) ASSUME_YES=1 ;;
      --no-model-download) NO_MODEL=1 ;;
      *) printf 'error: unknown option: %s\n\n' "$1" >&2; usage >&2; return 2 ;;
    esac
    shift
  done

  say "hyprwhispr installer"
  local distro; distro="$(detect_distro)"
  say "Detected system: $distro ($OS_RELEASE_FILE)"
  case "$distro" in
    unsupported)
      bad "unsupported distribution. This installer supports Fedora, Nobara and"
      info "Fedora-derived systems using dnf. No changes were made."
      print_summary; return 2 ;;
    fedora-atomic)
      bad "Fedora Atomic / image-based variant detected."
      info "Ordinary host package installation is not used on Atomic systems."
      info "Install the dependencies with 'rpm-ostree install' or inside a toolbox"
      info "(e.g. 'toolbox create && toolbox enter'), or use a non-Atomic Fedora."
      info "No changes were made."
      print_summary; return 2 ;;
    fedora-derived)
      warn "Fedora-derived system ($distro): treated like Fedora; not separately tested";;
  esac

  if [ "$CHECK_ONLY" = 1 ]; then
    assess_requirements
    print_summary
    [ "$FAIL" -eq 0 ]
    return $?
  fi

  say ""
  say "Dependency summary (before installation):"
  assess_requirements

  say ""
  say "Planned actions:"
  local pm; pm="$(pkg_manager)"; [ -n "$pm" ] || pm="dnf"
  info "install missing system packages via $pm"
  info "install the hyprwhispr Python app (pipx, or a venv fallback)"
  info "pull the Ollama model, build whisper.cpp, download the Whisper model"
  info "create ~/.config/hyprwhispr/config.json only if missing; write a binding snippet only if confirmed"
  if [ "$DRY_RUN" = 1 ]; then info "(dry-run: nothing will actually change)"; fi
  if [ "$DRY_RUN" = 0 ] && [ "$ASSUME_YES" = 0 ]; then
    if ! confirm "Proceed with installation?"; then
      warn "installation cancelled by user; no changes made"
      return 1
    fi
  fi

  install_build_and_audio_packages
  install_optional_packages
  install_python_app
  install_ollama_model
  install_whisper
  install_speech_model
  install_config
  install_binding

  if [ "$DRY_RUN" = 1 ]; then
    say ""
    say "Dry run complete; nothing was changed."
    return 0
  fi

  final_verify
  print_summary
  [ "$FAIL" -eq 0 ]
}

if [ "${HYPRWHISPR_INSTALL_LIB:-0}" = "1" ]; then
  : # sourced for testing; functions only
else
  main "$@"
  exit $?
fi
