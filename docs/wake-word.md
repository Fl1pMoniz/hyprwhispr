# Wake word (optional)

HyprWhispr can optionally be activated by speaking a wake word instead of
pressing the keyboard shortcut. **It is disabled by default**, and existing
shortcut-only installations are unaffected.

> Default wake word for new configurations: **`дідько`** — Ukrainian for "the
> devil", a mild, tongue-in-cheek curse (exact Unicode; preserved verbatim). It is
> stored in the config, never hard-coded.

Wake-word detection runs **entirely locally**. While waiting, no audio leaves the
machine and the LLM is never called until a command is captured.

## Activation modes

Set `wake_word_mode` in `~/.config/hyprwhispr/config.json` (or via the CLI):

| Mode | Behaviour |
|---|---|
| `shortcut` | keyboard push-to-talk only **(default)** |
| `wake_word` | wake word only |
| `both` | keyboard shortcut *and* wake word |
| `disabled` | no activation mechanism |

## Detection engines

HyprWhispr keeps the detector behind a small interface and ships **two** backends.
`wake_word_engine` selects one (`auto` by default).

| Engine | How it works | Phrase support | Cost |
|---|---|---|---|
| **`whisper`** (default via `auto`) | reuses your local whisper.cpp model: keeps a rolling ~2.5 s window and transcribes it **only when speech is present**, then matches the phrase | **any phrase in any language whisper supports** — including `дідько`; no training | higher CPU/GPU, ~hundreds of ms latency |
| **`openwakeword`** | openWakeWord neural wake-word model | its **English** pretrained phrases, or a custom-trained model | very low CPU |

`auto` prefers an openWakeWord model when one matches the phrase (lowest CPU),
and otherwise falls back to the whisper engine — so the default `дідько` works with
**no training and no extra downloads**, using the multilingual model you already
have.

### Licensing of the optional engine

[openWakeWord](https://github.com/dscripka/openWakeWord) is **optional**:

- **Code:** Apache-2.0.
- **Pre-trained models:** CC-BY-NC-SA-4.0 (**non-commercial**).

The default **whisper** engine uses nothing beyond the whisper.cpp + Whisper model
you already installed for the assistant.

## Commands

```bash
hyprwhispr wake-word show            # mode, phrase, engine and capability
hyprwhispr wake-word set "дідько"      # change the phrase (does NOT enable it)
hyprwhispr wake-word set "Olá assistente"
hyprwhispr wake-word set "Привет помощник"
hyprwhispr wake-word set "你好助手"
hyprwhispr wake-word enable          # mode = both (keeps the keyboard shortcut)
hyprwhispr wake-word disable         # mode = shortcut (restore the default)
hyprwhispr wake-word mode wake_word  # shortcut|wake_word|both|disabled
hyprwhispr wake-word check           # is a usable engine/model available?
hyprwhispr wake-word listen          # run the listener in the foreground
```

Changing the phrase never enables the feature; enabling is always explicit.

Install the optional openWakeWord engine (not needed for the default engine):

```bash
pipx inject hyprwhispr openwakeword   # recommended
# or, from a source checkout:  pip install '.[wakeword]'
```

Audio capture uses **`parec`** (from PipeWire/PulseAudio, already present on
Fedora/Nobara) and needs **no Python package**. Only if `parec` is unavailable
does it fall back to the optional `sounddevice` package.

## Support for a given phrase

| Case | Meaning | Examples |
|---|---|---|
| **Whisper (default)** | detected by local transcription; any language whisper supports; not acoustically verified here | `дідько`, `Olá assistente`, `Привет помощник`, `你好助手`, `こんにちはアシスタント` |
| **openWakeWord pretrained** | existing English model (optional engine) | `alexa`, `hey jarvis`, `hey mycroft`, `hey rhasspy`, `what's the weather` |
| **openWakeWord custom** | needs a model trained and mapped | any phrase not in the pretrained set |

The default `дідько` is handled by the **whisper** engine: recognised by
transcribing short audio and matching the word — so it needs **no training**.
`wake-word check` reports the active engine. Acoustic accuracy is **not verified**
by the automated tests; it depends on whisper, your microphone and noise.

## Custom openWakeWord models (optional)

Only needed if you want openWakeWord's lower CPU usage for a specific phrase:

1. Generate synthetic speech for the phrase with
   [`dscripka/synthetic_speech_dataset_generation`](https://github.com/dscripka/synthetic_speech_dataset_generation)
   (non-English is experimental).
2. Add negative data (speech/noise without the phrase).
3. Train with openWakeWord's
   [automatic training notebook](https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb).
4. Validate false activations and misses on held-out audio.
5. Place the `.onnx`/`.tflite` model on disk and map it:

   ```json
   {
     "wake_word": "дідько",
     "wake_word_engine": "openwakeword",
     "wake_word_models": { "дідько": "/home/you/models/suka.onnx" }
   }
   ```

## Configuration reference

| Key | Default | Meaning |
|---|---|---|
| `wake_word_mode` | `shortcut` | activation mode (see above) |
| `wake_word` | `дідько` | exact Unicode phrase |
| `wake_word_engine` | `auto` | `auto` \| `whisper` \| `openwakeword` |
| `wake_word_models` | `{}` | phrase → openWakeWord model id or `.onnx`/`.tflite` path |
| `wake_word_threshold` | `0.5` | openWakeWord score threshold (0–1) |
| `wake_word_window_seconds` | `2.5` | rolling audio window for the whisper engine |
| `wake_word_cooldown_seconds` | `2.0` | minimum gap between activations |
| `wake_word_command_seconds` | `6` | bounded command-listening window |
| `wake_word_feedback` | `true` | brief notification on detection |
| `wake_word_device` | `null` | optional capture device (a `parec` source name, or a `sounddevice` device) |

## Microphone lifecycle and privacy

- Nothing listens unless `wake_word_mode` is `wake_word`/`both` **and** you run
  `hyprwhispr wake-word listen`. There is **no daemon, service or autostart**.
- One audio stream is used for detection and command capture (no contention with
  push-to-talk). Frames are bounded and discarded.
- The whisper engine transcribes **only when there is speech energy**, so silence
  costs essentially nothing. During speech it writes a single rolling-window WAV
  under the runtime directory and **deletes it immediately** after transcription;
  no continuous or background audio is retained.
- While waiting, the LLM and tools are never invoked. All existing tool
  permissions, confirmations and safety checks are unchanged.
- Detection uses the system default input, or `wake_word_device`/`mic_target` when
  set (passed to `parec`).

`listen` runs in the foreground (`Ctrl+C` to stop). To start it on demand from
Hyprland, bind a key to `hyprwhispr wake-word listen`.

## Interaction styles

- **One-stage** — "`дідько, открой Firefox`": the whisper engine removes the wake
  phrase and sends the remainder ("открой Firefox") straight to the agent.
- **Two-stage** — say the wake word, wait for the brief cue, then say the command;
  the command window is recorded and processed normally.

A wake-word-only detection never reaches the agent; empty/silent commands are
ignored and the listener resumes.

## Accuracy, false activations and misses

Wake-word detection is **not perfect**. Expect occasional false activations and
missed detections depending on your voice, microphone, distance and noise. The
whisper engine may mis-transcribe a phrase; the openWakeWord engine's threshold
can be tuned. Automated tests here mock the detector and **do not** prove acoustic
accuracy — evaluate with your own audio (below).

## Evaluating real recognition (optional)

1. `hyprwhispr wake-word enable` then `hyprwhispr wake-word listen`.
2. Say the phrase several times; note how often it activates (and use one-stage vs
   two-stage). For openWakeWord, tune `wake_word_threshold`.
3. Test negative audio (speech without the phrase) and count false activations.
4. Vary speaker, speed and volume; watch idle CPU/memory with `top`/`ps`.
5. Do not commit microphone recordings.

## Troubleshooting

- **`status: engine_missing`** — no usable engine. Build whisper.cpp
  (`scripts/setup-whisper.sh`) or install openWakeWord.
- **`status: requires_custom`** — you chose `wake_word_engine: openwakeword` and
  the phrase has no model; train one or switch back to `whisper`.
- **`could not open the microphone`** — check PipeWire and `wake_word_device`
  (a `parec` source name). If `parec` is missing, install `pipewire-pulse`. If
  `sounddevice` is reported missing, install `python3-sounddevice` or use `parec`.
- **No activation** — lower the threshold (openWakeWord), speak clearly, or check
  that `hyprwhispr transcribe <wav>` works (the whisper engine depends on it).
- **Restore keyboard-only** — `hyprwhispr wake-word disable`.

## Notes on `дідько`

`дідько` is the exact default phrase and is preserved as Unicode throughout. With
the default `whisper` engine it is detected without any training — but "detected"
here means *transcribed and matched*; actual recognition still depends on whisper
and your audio conditions.
