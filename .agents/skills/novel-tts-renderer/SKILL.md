---
name: novel-tts-renderer
description: Creates, migrates, reviews, and validates per-book TTS render configuration for this project, including render/config.yaml, voices.yaml, voice_used.yaml, styles.yaml, Fish Audio and MiMo profiles, dry-run planning, and explicitly requested rendering. Use when asked to configure models or voices, prepare a book for rendering, troubleshoot render YAML, validate a render plan, assemble existing audio, or generate TTS.
compatibility: Requires the novel-tts project CLI, its standard book layout, and ffmpeg for synthesis or assembly.
---

# Novel TTS Renderer

Configure and operate the independent renderer without modifying semantic annotation data.

Before editing renderer files, read all of:

1. [Render configuration](../../../docs/render-configuration.md)
2. [Providers and models](../../../docs/render-providers.md)

Use those project documents as the canonical schema. Do not infer fields from obsolete per-profile voice-file layouts.

## Ownership boundary

Renderer work may create or update only `<book>/render/` files and generated renderer outputs. Do not modify:

- `source/`
- `processed/`
- `annotations/`
- `persons.yaml`
- `scenes.yaml`
- root `voices.yaml`

If annotation data is missing, invalid, uses `UNKNOWN`, or needs semantic correction, report it and switch to the annotator workflow rather than hiding the problem in render configuration.

## Human decisions

Treat these as user-owned decisions:

- provider and model;
- preset names, saved reference IDs, reference recordings, and voice descriptions;
- final narrator and character casting;
- privacy, budget, and permission to send text to a provider;
- whether to force regeneration or allow partial assembly;
- subjective audio approval.

You may propose a casting table from book context, but label it as a proposal. Do not invent provider-owned IDs, claim an unverified preset exists, or make paid requests merely because configuration was requested.

## Establish context

Inspect:

1. `<book>/persons.yaml`
2. all selected `<book>/annotations/*.yaml`
3. `<book>/scenes.yaml`
4. existing `<book>/render/` files
5. reference audio metadata and paths when clone sources are requested

Build the exact set of names used by selected annotations, including `NARRATOR` and `EXTRA`. Never configure a voice for `UNKNOWN` as a workaround.

Check available model IDs first when the requested model is unclear:

```bash
novel-tts render capabilities
```

## Configuration workflow

### 1. Define profiles

Write `render/config.yaml` with exact provider/model pairs and environment-variable names. Keep secrets out of YAML. Default to:

- `style_policy.unsupported: error`;
- `review.fail_on_review: true`;
- `review.fail_on_unknown: true`;
- non-streaming provider output in WAV;
- canonical output at 24 kHz mono s16 unless the user requests otherwise;
- `execution.max_chars_per_request: 200`.

Provider request fields must come from the provider guide. Reject unsupported combinations rather than replacing a model, voice kind, format, or stream mode.

### 2. Build the voice catalog

Write `render/voices.yaml`. For every used canonical name, define one or more source IDs. Every source must explicitly name its profile and kind.

Use only user-provided or already verified values for:

- `voice` preset names;
- `reference_id` values;
- `reference_audio` files and matching `reference_text`;
- text-design `description`.

Paths are relative to `render/voices.yaml`. Validate that reference files exist before planning.

The project casting policy keeps `EXTRA` on the narrator voice. Copy the complete `NARRATOR` source definitions to `EXTRA` and ensure their active selections resolve identically. If no narrator source exists, report the missing casting decision instead of inventing one.

### 3. Select active sources

Write `render/voice_used.yaml` with `default_profile` and optional per-person source IDs. Remember:

- override values are source IDs, not profile IDs or provider voice names;
- one source in the default/forced profile is selected automatically;
- zero or multiple matches are errors;
- `--profile` ignores person overrides and strictly forces that profile;
- mixed selections receive a hashed output target.

The current schema selects per person, not per emotion or segment. Do not document an unimplemented rule engine in book configuration.

### 4. Add custom style mappings only when needed

Write `render/styles.yaml` as `{}` when defaults suffice. Add mappings for annotation values not covered by the built-ins. Do not alter semantic annotations simply to fit a provider, and do not use `warn_and_omit` unless the user intentionally accepts omitted style controls.

### 5. Ignore generated data

Ensure `render/.gitignore` contains:

```gitignore
cache/
manifests/
output/
```

Do not delete existing cache or output unless the user explicitly asks. Configuration changes are handled by cache keys and output selection targets.

## Free validation gate

Always run these before any paid request:

```bash
novel-tts validate <book>
novel-tts render validate-config <book>
novel-tts render plan <book>
```

Use the same `--profile`, `--chapter`, `--scene`, and `--allow-review` options intended for the eventual run. `plan` is the final preflight because it compiles styles, splits text, validates provider-specific request fields, and reports cache state.

Repair renderer YAML errors. Do not remove honest annotation review state or assign a guessed speaker merely to make the plan pass.

Report at least:

- selected target and profiles;
- jobs and character count;
- cache hits/migrations/misses;
- unresolved casting or review blockers;
- whether any operation would call a paid API.

## Paid execution gate

Run synthesis only when the user explicitly asks to generate audio. Configuration, validation, planning, status, and assembly do not imply authorization to call an API.

Load credentials without printing them:

```bash
novel-tts render run <book> --env-file .env
```

Do not enable these options unless explicitly requested and explained:

- `--force`: discards matching cache entries and can repeat paid synthesis;
- `--allow-partial`: permits knowingly incomplete assembled audio;
- `--allow-review`: renders segments still marked for review.

After a run, inspect the manifest/status and report completed, failed, and assembly state. Do not describe a partial or unassembled result as complete.

## Reassembly and status

Reassembly uses existing segment WAV files and never calls a provider:

```bash
novel-tts render assemble <book>
novel-tts render status <book>
```

If planned segments are missing, keep the default blocking behavior. Use `--allow-partial` only on explicit request.

## Final checks

For configuration changes, run Ruff and tests only when source code or project-wide examples/tests were also changed. For ordinary per-book YAML work, configuration validation and the dry-run plan are the required checks.

A successful technical render still needs human listening review for casting, pronunciation, pacing, emotional quality, and scene transitions.
