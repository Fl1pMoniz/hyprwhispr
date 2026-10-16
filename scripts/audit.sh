#!/usr/bin/env bash
# Lightweight, dependency-free license/hygiene inventory for hyprwhispr.
#
# It performs deterministic checks only:
#   * no model weights, binaries or archives are present (tracked or untracked),
#   * no large blobs in Git history,
#   * no obvious secrets in source files,
#   * the runtime has no third-party Python dependencies,
#   * a list of the external commands the code invokes,
#   * the pinned external artifacts (whisper.cpp commit, model file).
#
# LIMITATION: this cannot detect copied code, cannot read model cards, and does
# not establish legal compliance. It is a starting point for human review, not a
# clearance. See docs/license-audit.md.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

issues=0
fail() { echo "  [FAIL] $*"; issues=$((issues + 1)); }
ok() { echo "  [ok]   $*"; }

# Tracked files plus untracked files that are not gitignored (respects .gitignore).
mapfile -t FILES < <(git ls-files -co --exclude-standard)

echo "== repository =="
echo "  tracked files:   $(git ls-files | wc -l | tr -d ' ')"
echo "  working-tree files checked: ${#FILES[@]}"

echo "== weights/binaries/archives present (must be empty) =="
bad="$(printf '%s\n' "${FILES[@]}" | grep -Ei '\.(bin|gguf|safetensors|pt|onnx|so|o|a|pyc|whl|tar|gz|zip|AppImage|deb|rpm)$|(^|/)models/' || true)"
if [ -n "$bad" ]; then echo "$bad" | sed 's/^/    /'; fail "artifact(s) found"; else ok "none"; fi

echo "== large blobs in Git history (>1MB, must be empty) =="
big="$(git rev-list --objects --all | awk '{print $1}' \
      | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize)' 2>/dev/null \
      | awk '$1=="blob" && $3>1048576 {print $3}')"
if [ -n "$big" ]; then echo "$big" | sed 's/^/    /'; fail "large blob in history"; else ok "none"; fi

echo "== secrets in source files (must be empty) =="
if printf '%s\0' "${FILES[@]}" | xargs -0 grep -nIE 'BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20}|sk-[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}|xox[baprs]-' 2>/dev/null; then
  fail "possible secret found"
else
  ok "none"
fi

echo "== runtime dependency declaration =="
deps="$(awk -F'=' '/^dependencies *=/{sub(/^ /,"",$2); print $2}' pyproject.toml)"
echo "  dependencies = ${deps:-<missing>}"
case "$deps" in
  *"[]"*) ok "standard library only" ;;
  *) fail "non-empty runtime dependencies: $deps" ;;
esac

echo "== external commands invoked by the code =="
grep -rhoE 'subprocess\.(run|Popen)\(\["[a-z][a-z0-9_-]+' src 2>/dev/null \
  | grep -oE '"[a-z][a-z0-9_-]+' | tr -d '"' | sort -u | sed 's/^/    /'

echo "== external tool references (curated) =="
grep -rhoE '"(zenity|rofi|notify-send|gtk-launch|gio|xdg-open|hyprctl|wpctl|pw-record|ffmpeg|wl-copy|pgrep|pkill|steam|kitty|opencode|ollama)"' src scripts 2>/dev/null \
  | tr -d '"' | sort -u | sed 's/^/    /'

echo "== pinned external artifacts =="
grep -hoE 'WHISPER_CPP_COMMIT:-[0-9a-f]+' scripts/*.sh 2>/dev/null | sed 's/^/    whisper.cpp commit: /'
grep -hoE 'ggml-[a-z]+\.en\.bin' scripts/*.sh 2>/dev/null | sort -u | sed 's/^/    model file: /'

echo
if [ "$issues" -eq 0 ]; then
  echo "audit: no automated hygiene issues found"
else
  echo "audit: $issues automated issue(s) found"
fi
echo "note: automated checks cannot prove code provenance or legal compliance."
exit "$issues"
