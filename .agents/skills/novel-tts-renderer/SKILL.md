---
name: novel-tts-renderer
description: Creates, migrates, reviews, and validates per-book mixed-profile TTS render configuration, including render targets, provider/model profiles, concrete voice sources, casting, natural-language style compilation, dry-run plans, cache-backed rendering, and complete assembly. Use when asked to configure models or voices, prepare a book for rendering, troubleshoot render YAML, validate a render plan, assemble existing audio, or explicitly generate TTS.
compatibility: Requires the novel-tts project CLI, its standard book layout, and ffmpeg for synthesis or assembly.
---

# Novel TTS Renderer

Configure and operate provider adapters without changing semantic annotation data. Before editing renderer files, read both [rendering documentation](../../../docs/rendering.md) and [provider documentation](../../../docs/providers.md).

## Ownership boundary

Renderer work may edit only `<book>/render/` configuration and generated outputs. Do not alter source, processed text, annotations, persons, or scenes to make rendering pass. If annotation is invalid or contains UNKNOWN, return to the annotator workflow.

Human-owned decisions include:

- target names and provider/model profiles;
- real preset/design/clone/reference data and permission to use it;
- narrator and character casting;
- credentials, privacy, cost, and permission to send text;
- final listening approval.

Never invent a reference ID or clone sample. Never make an API call merely because configuration was requested.

## Configuration workflow

1. Run `novel-tts validate <book>`.
2. Inspect `persons.yaml`, effective speakers, and existing `render/` YAML.
3. Run `novel-tts render providers`.
4. Set a stable `target`, `default_profile`, and one or more concrete profiles in `render/config.yaml`.
5. Record real executable sources in `render/voices.yaml`; each voice uses the default profile or an explicit `profile`.
6. Map every effective speaker to one voice ID in `render/voice_used.yaml`.
7. Ensure `render/.gitignore` ignores `cache/`, `manifests/`, and `output/`.

Multiple speakers may share one voice. Include NARRATOR and all used EXTRA variants. Never add UNKNOWN to casting.

## Mixed-profile model

Profiles contain only execution settings:

```yaml
target: main-mixed
default_profile: mimo-preset
profiles:
  mimo-preset:
    provider: mimo
    model: mimo-v2.5-tts
    api_key_env: MIMO_API_KEY
  mimo-design:
    provider: mimo
    model: mimo-v2.5-tts-voicedesign
    api_key_env: MIMO_API_KEY
```

Voice IDs are concrete sources, not abstract cross-provider containers:

```yaml
voices:
  narrator-designed:
    profile: mimo-design
    mode: design
    description: 平静、克制的近距离小说旁白声。
  supporting-preset:
    mode: preset
    voice: 白桦
```

Omitting `profile` selects `default_profile`. `voice_used.yaml` remains a simple speaker-to-voice map. Selection is per speaker only: do not add per-segment switching, automatic fallback, implicit source search, or capability matrices.

## MiMo modes

MiMo mode is explicit and must match the selected profile model:

```text
preset -> mimo-v2.5-tts -> voice
design -> mimo-v2.5-tts-voicedesign -> description
clone  -> mimo-v2.5-tts-voiceclone -> reference_audio
```

Use voice `instruction` only for optional persistent delivery guidance. Segment style stays in annotation as provider-neutral natural-language `direction` plus optional `tags_before` and `tags_after`. MiMo sends direction in the user message and wraps boundary tags into the assistant text. Clone paths are relative to `render/` unless absolute. Never put clone Base64 in YAML; the adapter creates the data URL at request time.

## Free validation gate

Before any API request, run:

```bash
novel-tts render validate <book>
novel-tts render plan <book>
```

For chapter-only work, use the same chapter in the plan and eventual run:

```bash
novel-tts render plan <book> --chapter 003
```

Report target, per-profile and total job/character/cache counts, missing casting, UNKNOWN blockers, and whether the next command would call an API. Validation and planning must not require credentials.

## Execution gate

Only an explicit user request to generate audio authorizes:

```bash
novel-tts render run <book> --env-file .env
```

The command calls each selected profile only for cache misses. Never print credentials. Each profile has its own shared HTTP client and concurrency/retry/timeout policy. If any job fails, final chapter/book assembly is blocked while successful cache entries remain reusable.

Reassembly never calls an API:

```bash
novel-tts render assemble <book>
novel-tts render status <book>
```

After execution, report completed/failed counts, assembly state, target output location, and whether human listening review remains. Technical success never replaces listening review for casting, pronunciation, pacing, provider transitions, loudness, and audio quality.
