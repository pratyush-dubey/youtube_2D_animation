# Cinematic audio architecture

The implemented first milestone changes audio from a late TTS step into a
shot-addressed production plan:

```text
storyboard + shots + characters
              |
         AudioDirector
              |
   audio_plan.json + emotion_curve.json
              |
     VoicePack + VoiceProvider
              |
      versioned audio package
```

## Implemented

- `VoicePack` metadata and a language-aware `VoicePackRegistry`.
- A provider-independent `VoiceProvider` contract.
- A local Piper provider that requires an explicit licensed ONNX model and
  never silently falls back to a lower-quality engine.
- Speech markup for emotion, pause, speed, pitch, emphasis, whisper and volume.
- A user-editable pronunciation dictionary.
- A consistent narrator identity and persistent character-to-voice map.
- Shot-level voice, foley, SFX, ambience, music and intentional-silence events.
- Era-aware source identifiers, stereo pan, gain, fades, priority and visual
  contact/action synchronization metadata.
- `audio_vNNN` version preservation and a dependency report.
- Pipeline execution of `AudioDirectorAgent` after storyboard planning and
  before voice generation.

## Honest dependency policy

An event in `audio_plan.json` is not evidence that its audio file exists.
`asset_available` and `production_ready` must be true before final mixing.
The catalog starts unavailable until a local file and its usage license are
recorded. Authored silence is allowed, but is never substituted as a music file.

Piper is the selected local engine. It needs both a `.onnx` model and its
`.onnx.json` configuration. Set the model path in `.env`:

```text
TTS_PROVIDER=piper
PIPER_MODEL_PATH=D:\AI_VIDEO_GENERATOR\voices\your-approved-voice.onnx
```

## Development proof

Build the 30-second 1980s Bengaluru bank plan:

```powershell
python -m tools.build_audio_architecture_test
```

Review:

```text
output/audio_bank_test/audio/audio_plan.json
output/audio_bank_test/audio/reports/dependency_report.json
```

The next milestones are asset-backed SFX/foley/ambience resolution, music
direction, the multitrack mixer/mastering report, lip sync, audio QA and the
editor timeline. They remain gated rather than represented by fake files.
