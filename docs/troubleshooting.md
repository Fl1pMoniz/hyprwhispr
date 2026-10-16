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

## "No speech detected" or "Too short"
hyprwhispr rejects clips that are shorter than `min_record_ms` (default 300 ms)
or quieter than `silence_threshold_db` (default −50 dBFS) *before* running
whisper, which removes the silence-hallucination problem. If a genuine short
command ("stop") is being rejected, lower `min_record_ms`; if you speak quietly,
lower `silence_threshold_db` (for example to −55).

## The assistant asks which app I mean
That is the ambiguity guard: more than one installed app matched with no clear
winner, so it asked instead of guessing. Answer with the name (e.g. "KCalc"), and
it will act. Use `hyprwhispr resolve "<name>"` to see the ranked candidates.

## Follow-up requests like "close it" don't work
Context is stored per session and expires after `session_ttl_minutes`. Check it
with `hyprwhispr session`; if it is empty (for example after 30 idle minutes) the
reference is gone. Say the target explicitly, or raise `session_ttl_minutes`.

## The model keeps choosing the wrong tool
Tool selection is model-driven, so quality depends on the model. Measure it with
`python scripts/benchmark.py --live`, and try a larger model
(`hyprwhispr model large`) if the small default is not accurate enough.


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
