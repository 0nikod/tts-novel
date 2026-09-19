---
name: novel-tts-annotator
description: Annotates preprocessed Chinese novel chapters for TTS by assigning speakers, character prominence, text types, explicit speaking styles, and linear scenes; updates persons.yaml, scenes.yaml, and annotations/*.yaml, then validates them. Use when asked to mark, annotate, continue, inspect, or correct a novel under books/ for the novel TTS workflow.
compatibility: Requires the novel-tts project CLI and its standard book directory layout.
---

# Novel TTS Annotator

Annotate one book in numeric chapter order. The source text is immutable. Never create `speaker_id` values. Annotation output is provider-neutral: do not read or modify render configuration, voice catalogs, voice selections, or provider-specific request data.

`src/novel_tts/annotation_schema.yaml` is the source of truth for all annotation type, person role, system name, review reason, style field, and style value vocabularies. Consult its exported constants rather than maintaining or inventing values in this skill. In particular, every non-null style value must occur under its field in `STYLE_VALUES`; never create a free-form short English value.

Read [annotation rules](references/annotation-rules.md) before making semantic decisions. Read [YAML examples](references/yaml-examples.md) when creating or repairing files.

## Inputs

For chapter `<C>`, read all of:

1. `<book>/persons.yaml`
2. `<book>/scenes.yaml`
3. `<book>/processed/<C>.txt`
4. `<book>/annotations/<C>.yaml` when it already exists
5. The end of the previous processed chapter and its annotation when continuity is unclear

Do not read only isolated dialogue lines. Speaker, prominence, and scene decisions require surrounding and book-level context.

## Preconditions

1. Confirm the book has the standard structure.
2. Confirm chapters are being handled in numeric order. Do not silently skip an earlier unannotated chapter.
3. If processed text is missing, run:

```bash
novel-tts preprocess <book> --chapter <C>
```

4. If preprocessing reports broken or ambiguous quotation boundaries, preserve its output and mark affected segments for review using the schema's corresponding preprocessing reason.

## Workflow

### 1. Establish context

Build a working list of canonical person names and aliases from `persons.yaml`. Inspect existing scene IDs and identify the last scene before this chapter. If an existing annotation is present, preserve confirmed human choices unless they violate the schema or the user explicitly asks for re-annotation.

### 2. Classify every processed line

For every line, determine:

- canonical `name`
- `type` from `TEXT_TYPES`
- explicit `style`, otherwise `null`
- linear `scene_id`

Every processed line must be covered exactly once. A segment can contain only consecutive lines.

Use the appropriate reserved name from `SYSTEM_NAMES` for narration or a genuinely unresolved person. Use canonical names in annotations, never aliases.

Treat paratext sections such as `后记`, `作者后记`, `译者后记`, `作者注`, `译者注`, editorial notes, acknowledgements, and similar non-story material as a narrator-only region: assign the narrator system name to every line in the section, including quoted speech, signatures, and attributed remarks. Continue to classify each line's `type` from its textual form. Do not add people to `persons.yaml` solely because they are named or quoted in such a section.

### 3. Classify character prominence and maintain people

Choose roles only from `PERSON_ROLES`, using the semantic guidance in the annotation rules. Judge narrative importance, recurrence, and likely future relevance from all available book context; do not classify by a rigid appearance-count threshold. When uncertain between a recurring distinct character and an incidental one, keep the person distinct rather than prematurely merging them.

Represent all minor characters with one canonical person:

```yaml
- name: EXTRA
  aliases: []
  role: minor
```

Use `name: EXTRA` in annotations for every confidently identified minor speaker. Do not add each minor person separately and do not put distinct people's names into `EXTRA.aliases`, because they are not aliases of one identity. This deliberate aggregation is for TTS casting; it does not mean the story characters are the same person. If a previously aggregated character later proves recurring or consequential, create a distinct person with the appropriate schema role and update all of that character's earlier annotations.

For each distinct non-minor person established by the text, append an item containing `name`, `aliases`, and `role` to the `persons` list in `persons.yaml`. Add genuine textual variants under `aliases`. Do not create separate people for an alias, title, nickname, or pronoun. Do not declare reserved system names in `persons.yaml`.

Do not invent biography, role, alias, or identity from weak evidence. Use the unknown system name with human review when uncertainty could change whether the speaker is `EXTRA` or a distinct character. Uncertainty only about which incidental minor person spoke may be annotated as `EXTRA` when that distinction has no effect on casting or narrative continuity.

### 4. Maintain scenes

A scene is a linear narrative event, not merely a place or time label. Continue the preceding scene when the event, conversation, and principal relationships remain continuous. Create a new scene for a clear narrative jump or independent event.

Allocate new IDs monotonically (`S0001`, `S0002`, ...). Update each scene range and concise summary in `scenes.yaml`. A scene may cross a chapter boundary and then uses a list of chapter ranges. Scene ranges must not overlap or move backwards.

### 5. Record uncertainty

Use `review: true` plus exactly one suitable value from `REVIEW_REASONS`. Prefer an honest reviewed unknown speaker over an unsupported speaker guess. Do not use review merely because inference required context; use it when meaningful uncertainty remains.

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

Repair structural errors in `persons.yaml`, `scenes.yaml`, or the chapter annotation. Do not eliminate semantic uncertainty merely to make validation pass. Report remaining warnings and all review items to the user.

## Hard constraints

- Do not rewrite, normalize, translate, or correct正文.
- Do not infer emotion, volume, pace, whispering, or vocal actions unless explicitly stated in the text.
- Do not use location or time alone as a reason to split a scene.
- Do not create non-contiguous segment line lists.
- Do not assign character names inside narrator-only paratext sections.
- Do not place person details, scene summaries,正文, voices, or speaker IDs in annotations.
- Do not place location/time metadata in `scenes.yaml`.
- Do not read or modify renderer files and do not call a TTS service. Renderer setup belongs to the `novel-tts-renderer` skill.
