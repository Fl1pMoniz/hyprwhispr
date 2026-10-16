# Troubleshooting

Run `scripts/verify.sh` first; it reports what is missing.

## The hotkey does nothing
- Check the binding is present: `hyprctl binds | grep -i hyprwhispr`.
- Re-read the keybind example: `bind` = press, `bindr` = release.
- Make sure `hyprwhispr` is on your `PATH` (test with `hyprwhispr version`).

## Recording starts but nothing is transcribed
- The wrong input device is the usual cause. `hyprwhispr list-mics`, then pin the
  device with `mic_target` (see `docs/configuration.md`).
- Confirm the mic actually captures: `hyprwhispr mictest`. If it reports a very
  low level, check the headset's hardware mute and the system input volume
  (`wpctl set-volume <id> 1.0`, `wpctl set-default <id>`).
- The default source may be a webcam mic that is silent.

## "whisper binary not found" / "whisper model not found"
Run `scripts/setup-whisper.sh` and `scripts/download-models.sh`.

## "Local model call failed"
- Is Ollama running? `curl http://127.0.0.1:11434/api/version`.
- Is the model pulled? `ollama pull qwen3:4b`.
- Check `logs/audit.jsonl` for the error.

## Out of VRAM / other apps stutter
- Switch to a smaller model: `hyprwhispr model small`.
- Move speech recognition off the GPU: set `"whisper_gpu": false`.
- Lower `keep_alive` so the model unloads sooner.

## Confirmation dialogs never appear
The gate needs `zenity` or `rofi`. Without one it denies the action and logs
`Action blocked`. Install one, or avoid the high-impact tools.

## A new app or game is missing from the list
Run `hyprwhispr refresh-apps`.

## Where are my files?
- Config: `~/.config/hyprwhispr/config.json`
- Data: `~/.local/share/hyprwhispr/` (notes, logs, cache, whisper.cpp, models)
