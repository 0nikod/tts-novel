---
name: novel-tts-renderer
description: Creates, reviews, and validates per-book private custom TTS render configuration, voice catalogs, casting, style mappings, dry-run plans, cache-backed rendering, and complete assembly. Use when asked to configure voices, prepare rendering, troubleshoot render YAML, validate a plan, assemble existing audio, or explicitly generate TTS.
compatibility: Requires the novel-tts project CLI, its standard book layout, and ffmpeg for synthesis or assembly.
---

# Novel TTS Renderer

Configure and operate the single private custom TTS backend without changing semantic annotation data. Read [rendering documentation](../../../docs/rendering.md) before editing renderer files.

## Ownership boundary

Renderer work may edit only `<book>/render/` configuration and generated outputs. Do not alter source, processed text, annotations, persons, or scenes to make a render pass. If annotation is invalid or contains UNKNOWN, return to the annotator workflow.

Human-owned decisions include:

- private endpoint and model;
- actual reference IDs/text and other model-specific voice fields;
- narrator and character casting;
- credentials, privacy, and permission to send text;
- final listening approval.

Never invent a real reference ID or make an API call merely because configuration was requested.

## Configuration workflow

1. Run `novel-tts validate <book>`.
2. Inspect `persons.yaml`, effective speakers in annotations, and existing `render/` YAML.
3. Set the private endpoint/model/runtime values in `render/config.yaml`.
4. Record all available sources in `render/voices.yaml` under stable voice IDs.
5. Map each effective speaker to a voice ID in `render/voice_used.yaml`.
6. Keep `render/styles.yaml` as `{}` unless the private model needs canonical style-value overrides.
7. Ensure `render/.gitignore` ignores `cache/`, `manifests/`, and `output/`.

Multiple speakers may share one voice. Include every effective speaker, including NARRATOR and used EXTRA variants. Never add UNKNOWN to casting.

Voice fields beyond the local voice ID belong to the custom backend and are sent as private-model voice parameters. Preserve user-provided values exactly.

## Free validation gate

Before any API request, run:

```bash
novel-tts render validate <book>
novel-tts render plan <book>
```

For a chapter-only operation, use the same chapter in the plan and eventual run:

```bash
novel-tts render plan <book> --chapter 003
```

Report job count, character count, cache hits/misses, missing casting, UNKNOWN blockers, and whether the next command would call the API.

## Execution gate

Only an explicit user request to generate audio authorizes:

```bash
novel-tts render run <book> --env-file .env
```

The command calls the API only for cache misses. Do not print credentials. If any job fails, final chapter/book assembly is blocked while successful cache entries remain reusable.

Reassembly never calls the API:

```bash
novel-tts render assemble <book>
novel-tts render status <book>
```

After execution, report completed/failed counts, assembly state, and output location. Technical success still requires human listening review for casting, pronunciation, pacing, and audio quality.
