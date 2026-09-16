---
name: novel-tts-annotator
description: Annotates preprocessed Chinese novel chapters for TTS by assigning speakers, text types, explicit speaking styles, and linear scenes; updates persons.md, scenes.yaml, and annotations/*.yaml, then validates them. Use when asked to mark, annotate, continue, inspect, or correct a novel under books/ for the novel TTS workflow.
compatibility: Requires the novel-tts project CLI and its standard book directory layout.
---

# Novel TTS Annotator

Annotate one book in numeric chapter order. The source text is immutable. Never create renderer data or `speaker_id` values.

Read [annotation rules](references/annotation-rules.md) before making semantic decisions. Read [YAML examples](references/yaml-examples.md) when creating or repairing files.

## Inputs

For chapter `<C>`, read all of:

1. `<book>/persons.md`
2. `<book>/scenes.yaml`
3. `<book>/processed/<C>.txt`
4. `<book>/annotations/<C>.yaml` when it already exists
5. The end of the previous processed chapter and its annotation when continuity is unclear

Do not read only isolated dialogue lines. Speaker and scene decisions require surrounding context.

## Preconditions

1. Confirm the book has the standard structure.
2. Confirm chapters are being handled in numeric order. Do not silently skip an earlier unannotated chapter.
3. If processed text is missing, run:

```bash
novel-tts preprocess <book> --chapter <C>
```

4. If preprocessing reports broken or ambiguous quotation boundaries, preserve its output and mark affected segments with `review: true` and `review_reason: preprocess_error`.

## Workflow

### 1. Establish context

Build a working list of canonical person names and aliases from `persons.md`. Inspect existing scene IDs and identify the last scene before this chapter. If an existing annotation is present, preserve confirmed human choices unless they violate the schema or the user explicitly asks for re-annotation.

### 2. Classify every processed line

For every line, determine:

- canonical `name`
- `type`: `narration`, `dialogue`, or `thought`
- explicit `style`, otherwise `null`
- linear `scene_id`

Every processed line must be covered exactly once. A segment can contain only consecutive lines.

Use `NARRATOR` for narration and `UNKNOWN` when the person genuinely cannot be resolved. Use canonical names in annotations, never aliases.

### 3. Maintain people

When the text establishes a new named person, add a `# name` section to `persons.md`. Add textual variants under `aliases`. Do not create separate people for an alias, title, nickname, or pronoun. Do not declare `NARRATOR` or `UNKNOWN` in `persons.md`.

Do not invent biography, role, alias, or identity from weak evidence. For unresolved identity use `UNKNOWN` and human review.

### 4. Maintain scenes

A scene is a linear narrative event, not merely a place or time label. Continue the preceding scene when the event, conversation, and principal relationships remain continuous. Create a new scene for a clear narrative jump or independent event.

Allocate new IDs monotonically (`S0001`, `S0002`, ...). Update each scene range and concise summary in `scenes.yaml`. A scene may cross a chapter boundary and then uses a list of chapter ranges. Scene ranges must not overlap or move backwards.

### 5. Record uncertainty

Use `review: true` plus exactly one suitable reason:

- `ambiguous_speaker`
- `ambiguous_type`
- `ambiguous_style`
- `ambiguous_scene`
- `unknown_character`
- `preprocess_error`

Prefer an honest reviewed `UNKNOWN` over an unsupported speaker guess. Do not use review merely because inference required context; use it when meaningful uncertainty remains.

### 6. Write annotations

Write `<book>/annotations/<C>.yaml`. Merge adjacent lines only when all of these match exactly:

- `name`
- `type`
- `style`
- `scene_id`
- review state and reason

Never copy正文 into YAML. Never alter `source/*.txt` or `processed/*.txt` while annotating.

### 7. Validate and repair

Run:

```bash
novel-tts validate <book> --chapter <C>
```

Repair structural errors in `persons.md`, `scenes.yaml`, or the chapter annotation. Do not eliminate semantic uncertainty merely to make validation pass. Report remaining warnings and all review items to the user.

## Hard constraints

- Do not rewrite, normalize, translate, or correct正文.
- Do not infer emotion, volume, pace, whispering, or vocal actions unless explicitly stated in the text.
- Do not use location or time alone as a reason to split a scene.
- Do not create non-contiguous segment line lists.
- Do not place person details, scene summaries,正文, voices, or speaker IDs in annotations.
- Do not place location/time metadata in `scenes.yaml`.
- Do not create a renderer or call a TTS service.
