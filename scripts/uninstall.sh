#!/usr/bin/env bash
# Remove hyprwhispr's data and configuration. Nothing else is touched: your
# Ollama installation, models, Hyprland config and OpenCode are left alone.
set -euo pipefail

DATA_DIR="${HYPRWHISPR_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/hyprwhispr}"
CONFIG_DIR="${HYPRWHISPR_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/hyprwhispr}"

echo "This will delete:"
echo "  $DATA_DIR   (whisper.cpp build, models, notes, logs)"
echo "  $CONFIG_DIR (config.json)"
echo
echo "It will NOT remove: Ollama or its models, your Hyprland keybinding, or OpenCode."
printf "Continue? [y/N] "
read -r reply </dev/tty || reply="n"
case "$reply" in
  [yY]*) ;;
  *) echo "Aborted."; exit 0 ;;
esac

rm -rf "$DATA_DIR" "$CONFIG_DIR"
echo "Removed hyprwhispr data and config."
echo
echo "Remove the hold-to-talk binding from your Hyprland config and reload:"
echo "  hyprctl reload"
echo
echo "If you installed the Python package itself, remove it with:"
echo "  pipx uninstall hyprwhispr   # or: pip uninstall hyprwhispr"
