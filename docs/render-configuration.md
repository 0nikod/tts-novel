# Render configuration

This document is the canonical guide for configuring the renderer for one book. Renderer data is isolated under `<book>/render/`; it must not change source text or annotation data.

Provider-specific models and request fields are documented in [render-providers.md](render-providers.md).

## Responsibility boundary

A human owns the creative and paid-service decisions:

- provider and model;
- actual preset names, saved reference IDs, reference recordings, and voice descriptions;
- final casting for narrator and characters;
- API budget, privacy, and permission to send the text to a provider;
- final listening approval.

An agent may inspect annotations, propose a casting table, write YAML, and run free validation commands. It must not invent credentials or reference IDs, silently replace an incompatible voice, or make a paid request unless the user explicitly asks it to render.

## Prerequisites

Before configuring rendering, the book should have valid:

```text
<book>/processed/*.txt
<book>/annotations/*.yaml
<book>/persons.yaml
<book>/scenes.yaml
```

Run structural validation first:

```bash
novel-tts validate <book>
```

The optional root `<book>/voices.yaml` is a legacy reference-ID map. The independent renderer does not read it.

## Directory layout

```text
<book>/render/
├── config.yaml       # profiles and renderer-wide policies
├── voices.yaml       # available sources for every speaker
├── voice_used.yaml   # default profile and per-speaker source selection
├── styles.yaml       # optional custom style mappings
├── cache/            # normalized segment cache; ignored by Git
├── manifests/        # progress and request metadata; ignored by Git
└── output/           # audio, timelines, subtitles, and snapshots; ignored by Git
```

A suitable `render/.gitignore` is:

```gitignore
cache/
manifests/
output/
```

## `config.yaml`

A complete configuration has this shape:

```yaml
profiles:
  mimo-preset:
    provider: mimo
    model: mimo-v2.5-tts
    api_key_env: MIMO_API_KEY
    request:
      format: wav
      stream: false
    concurrency: 2
    timeout_seconds: 120
    retries: 4
    style_policy:
      unsupported: error

output:
  sample_rate: 24000
  channels: 1
  sample_format: s16
  final_format: mp3

assembly:
  chunk_gap_ms: 0
  dialogue_gap_ms: 180
  narration_gap_ms: 260
  scene_gap_ms: 800
  chapter_gap_ms: 1500

execution:
  max_chars_per_request: 200
  manifest_flush_interval_seconds: 1.0

review:
  fail_on_review: true
  fail_on_unknown: true

timeline:
  enabled: true
  include_silence_events: true
  subtitles:
    formats: [srt, vtt]
    show_speaker: true
    include_narration: true
```

Only `profiles` is required. Omitted sections use the defaults shown below.

### Profiles

Each profile names one concrete provider/model combination. A profile does not select voices; sources in `voices.yaml` refer to it.

| Field | Default | Meaning |
|---|---:|---|
| `provider` | required | Registered provider ID, currently `mimo` or `fish_audio` |
| `model` | required | Exact registered model ID |
| `api_key_env` | required | Environment variable name, never the secret itself |
| `request` | `{}` | Provider-specific request options |
| `concurrency` | `1` | Maximum simultaneous requests for this profile |
| `timeout_seconds` | `120` | Per-request timeout |
| `retries` | `4` | Retries permitted by the HTTP safety policy |
| `style_policy.unsupported` | `error` | `error` or explicit `warn_and_omit` |

Keep `unsupported: error` unless omission is an intentional, reviewed policy. It prevents a style from disappearing without blocking the render.

### Output

| Field | Default | Supported values |
|---|---:|---|
| `sample_rate` | `24000` | Positive integer |
| `channels` | `1` | Positive integer |
| `sample_format` | `s16` | Currently only `s16` |
| `final_format` | `wav` | `wav`, `mp3`, `opus`, or `m4a` |

Every provider response is normalized to canonical PCM WAV before caching. Full-book output is additionally transcoded when `final_format` is not `wav`. Timelines use PCM frames from the WAV, not an estimated duration.

### Assembly gaps

All values are non-negative milliseconds:

| Field | Default | Applied after |
|---|---:|---|
| `chunk_gap_ms` | `0` | An internal chunk of the same annotation segment |
| `dialogue_gap_ms` | `180` | A dialogue segment when the next job stays in the scene |
| `narration_gap_ms` | `260` | A narration/thought segment when the next job stays in the scene |
| `scene_gap_ms` | `800` | The last job before a scene change |
| `chapter_gap_ms` | `1500` | The last job before a chapter change |

Chapter and scene changes take precedence over text-type gaps.

### Execution

`max_chars_per_request` limits provider request size. Longer annotation segments are split at Chinese or English sentence punctuation, then at minor punctuation, with a hard split only as a last resort. `vocal_action_before` is retained only on the first chunk and `vocal_action_after` only on the last.

`manifest_flush_interval_seconds` controls progress-file write frequency. `0` permits a write after every completion.

### Review policy

With the safe defaults, `review: true` and `UNKNOWN` prevent all API calls for the plan. `--allow-review` only overrides `fail_on_review`; it does not invent a voice for `UNKNOWN`.

### Timeline and subtitles

Supported subtitle formats are `srt` and `vtt`. Book, chapter, and scene timelines use the corresponding WAV-relative PCM frame positions. Chapter and scene segment records also include full-book positions after a complete-book assembly.

## `voices.yaml`

This file is a catalog of available sources, not the active selection:

```yaml
voices:
  小明:
    mimo-main:
      profile: mimo-preset
      kind: preset
      voice: 白桦

    fish-saved:
      profile: fish-s2-pro
      kind: saved_reference
      reference_id: provider-owned-reference-id

  NARRATOR:
    mimo-main:
      profile: mimo-preset
      kind: preset
      voice: 冰糖

  EXTRA:
    mimo-main:
      profile: mimo-preset
      kind: preset
      voice: 冰糖
```

The first-level key must be a canonical annotation name. Include every name actually used by the selected annotations, including `NARRATOR` and `EXTRA` where applicable. Reusing the active narrator voice for `EXTRA` is the default recommendation, not a schema requirement; an explicitly user-approved separate `EXTRA` voice is valid.

Source IDs such as `mimo-main` are local stable labels. They are not profile IDs or provider voice names.

### Voice kinds

#### Preset

```yaml
source-id:
  profile: mimo-preset
  kind: preset
  voice: provider-preset-name
```

#### Saved provider reference

```yaml
source-id:
  profile: fish-s2-pro
  kind: saved_reference
  reference_id: provider-owned-reference-id
```

#### Inline clone

Paths are resolved relative to `render/voices.yaml`, normally the `render/` directory:

```yaml
source-id:
  profile: fish-s2-pro
  kind: inline_clone
  reference_audio: references/person.wav
  reference_text: 与参考音频完全对应的文本
```

Fish requires `reference_text`. MiMo clone accepts WAV or MP3 according to the current capability registry.

#### Text design

```yaml
source-id:
  profile: mimo-design
  kind: text_design
  description: 沉稳、清晰的成年男性声音。
```

The source kind must be supported by the exact model referenced by its profile. The renderer rejects incompatible combinations before an API request.

### Multiple sources in one profile

A person may have several sources under the same profile:

```yaml
voices:
  小明:
    preset-a:
      profile: mimo-preset
      kind: preset
      voice: 白桦
    preset-b:
      profile: mimo-preset
      kind: preset
      voice: 苏打
```

This is valid only when `voice_used.yaml` explicitly selects one. Otherwise profile-based resolution is ambiguous and fails; there is no automatic fallback.

## `voice_used.yaml`

```yaml
default_profile: mimo-preset
voices:
  小明: preset-b
```

`default_profile` must name a profile from `config.yaml`. Each value under `voices` is a source ID under that specific person in `voices.yaml`.

Selection is deterministic:

1. When `--profile PROFILE` is supplied, per-person overrides are ignored and every used person must have exactly one source in that profile.
2. Otherwise, an explicit per-person source in `voice_used.yaml` wins, even if it belongs to another profile.
3. Otherwise, the person must have exactly one source in `default_profile`.
4. Zero or multiple matches are errors; the renderer never substitutes another voice.

A render with no overrides uses the default profile as its target directory name. Mixed selections use a stable selection hash, for example `mixed-a1b2c3d4e5`, so different casts do not overwrite each other.

Selection is currently per person, not per emotion or segment. Annotation style changes model performance instructions but does not switch sources.

## `styles.yaml`

This optional file overrides mappings from provider-neutral annotation style values to provider controls. The canonical annotation fields and values are defined in `src/novel_tts/annotation_schema.yaml`; overrides may remap those values, but they do not extend the annotation vocabulary. An empty file can contain:

```yaml
{}
```

Example:

```yaml
mimo:
  emotion:
    sad: 低落、沮丧
  delivery:
    whisper: 轻声、低语
  vocal_action_before:
    laugh: 轻笑

fish_audio:
  emotion:
    sad: sad
  delivery:
    whisper: whispering
  pace:
    slow: 0.75
  volume_db:
    low: -4
```

MiMo string values become natural-language instructions. MiMo vocal actions become parenthesized inline actions. Fish string values become bracket tags; custom Fish pace and `volume_db` values must be numeric.

Built-in mappings currently cover:

- emotion: `angry`, `calm`, `excited`, `happy`, `nervous`, `sad`, `shocked`;
- delivery: `scolding`, `shout`, `whisper`;
- volume: `high`, `low`;
- pace: `fast`, `slow`;
- vocal actions: `laugh`, `sigh`, `deep_breath`.

Do not edit annotations merely to conceal an unsupported provider style. Either add an intentional mapping, select `warn_and_omit`, or keep the blocking error.

## Credentials

Store only the environment-variable name in `config.yaml`:

```yaml
api_key_env: MIMO_API_KEY
```

A local `.env` may contain:

```dotenv
MIMO_API_KEY=secret-value
FISH_AUDIO_API_KEY=secret-value
```

`.env` is ignored by Git. Load it safely with:

```bash
novel-tts render run <book> --env-file .env
```

Existing process environment values are not overwritten. Never print, snapshot, or commit the secret.

## Safe workflow

Configuration and planning do not call a paid API:

```bash
novel-tts validate <book>
novel-tts render capabilities
novel-tts render validate-config <book>
novel-tts render plan <book>
```

Use `--profile`, `--chapter`, or `--scene` to validate the same target that will be rendered. Treat `plan` as the final request preflight because it compiles styles, splits text, validates provider request fields, and reports jobs, characters, and cache state.

Only after the user approves casting and paid execution:

```bash
novel-tts render run <book> --env-file .env
```

Useful options:

```text
--profile PROFILE    Strictly force a profile for every speaker
--chapter CHAPTER    Render one chapter
--scene SCENE        Render one scene
--allow-review       Permit review segments, but not unresolved UNKNOWN speakers
--force              Delete matching cache entries and pay to regenerate them
--allow-partial      Explicitly permit assembly when some planned jobs failed
```

`--force` and `--allow-partial` are exceptional operations. Do not enable them silently.

Reassembly never calls a provider:

```bash
novel-tts render assemble <book>
novel-tts render status <book>
```

## Reproducibility and outputs

A full output normally contains:

```text
render/output/<target>/
├── book.wav
├── book.<final-format>
├── timeline.json
├── subtitles.srt
├── subtitles.vtt
├── segments/<chapter>/
├── scenes/
├── chapters/
├── timelines/scenes/
├── timelines/chapters/
└── snapshots/
```

The snapshot directory copies the selected source, processed text, annotations, people, scenes, and all four render YAML inputs, with SHA-256 values in its manifest. The render manifest records the selected source, concrete voice details, chunk indexes, cache key, request ID, attempt count, elapsed time, completion state, and whether assembly was partial.

By default, any failed planned segment prevents assembly and stale assembled outputs are removed. Partial assembly requires the explicit `--allow-partial` option.

## Common failures

- **No voice configured**: add the canonical person to `voices.yaml`.
- **No source for the default profile**: add one or select an existing source in `voice_used.yaml`.
- **Multiple sources for a profile**: select one explicitly per person or use a stricter `--profile` catalog.
- **Unsupported voice kind**: use a model that supports that kind; do not silently convert clone to preset.
- **Unsupported style value**: add a reviewed `styles.yaml` mapping or correct the semantic annotation.
- **Missing API environment variable**: supply it in the environment or via `--env-file`.
- **Missing ffmpeg**: install `ffmpeg` before rendering.
- **Review/UNKNOWN errors**: return to annotation review instead of assigning an arbitrary voice.
