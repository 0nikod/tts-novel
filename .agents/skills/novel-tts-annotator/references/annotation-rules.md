# Annotation Rules

## Canonical vocabulary

`src/novel_tts/annotation_schema.yaml` is the sole source of truth for annotation types, person roles, reserved system names, review reasons, style fields, and style values. Use `TEXT_TYPES`, `PERSON_ROLES`, `SYSTEM_NAMES`, `REVIEW_REASONS`, `STYLE_FIELDS`, and `STYLE_VALUES` from that module; this reference explains their semantics but does not define a separate vocabulary. Renderer mappings, including `render/styles.yaml`, never extend the annotation taxonomy.

## Speaker (`name`)

Use the canonical `name` from the `persons` list in `persons.yaml`.

Evidence priority:

1. Explicit speech attribution attached to the quotation.
2. A continuing two-person exchange with an unambiguous turn pattern.
3. Actions or forms of address that uniquely identify the speaker.
4. Broader scene context.

Do not infer a speaker solely from stereotyped personality, gender, or likely behavior. If multiple candidates remain plausible, use the unknown system name with review for an ambiguous speaker.

Narrative prose normally uses the narrator system name. A first-person narrator still uses that name for narration; use the canonical character name only for their direct dialogue or represented thought.

### Narrator-only paratext

When a section is headed or clearly identified as `后记`, `作者后记`, `译者后记`, `作者注`, `译者注`, an editorial note, acknowledgements, or similar non-story material, assign the narrator system name to every line until that section ends. This override also applies to quoted speech, signatures, names, and attributed remarks inside the section. Preserve the normal `type` decision based on textual form; only the speaker name is forced.

Do not add an author, translator, editor, relative, or other person to `persons.yaml` solely because they appear in narrator-only paratext. If the same person independently appears as a character in the story, their story occurrences still follow the normal speaker rules.

## Character prominence and extras

Choose roles from `PERSON_ROLES`. Semantically, `main` drives the central narrative, `secondary` is recurring or consequential enough to preserve a distinct identity and voice, and `minor` is an infrequent incidental extra that does not need an individual TTS voice.

Importance and recurrence matter more than a raw number of lines. Use available later chapters and existing annotations to avoid treating a temporarily absent important character as minor. In a borderline case, preserve a distinct character as `secondary`.

All minor characters intentionally collapse to the single canonical person `EXTRA` (`role: minor`) in `persons.yaml` and annotations. Distinct minor people's names are not aliases of `EXTRA`; do not add them to its alias list. A clear attribution to an incidental person is sufficient to use `EXTRA` and does not require review. If context later elevates that person, add the proper canonical person and retroactively replace their `EXTRA` annotations.

Use the unknown system name with review when the unresolved speaker could be a main/secondary character rather than an extra. If every plausible speaker is incidental and distinguishing them has no effect on casting or continuity, use `EXTRA` without inventing an identity.

Voice assignment for `EXTRA` is a renderer concern. Do not read or modify voice mappings while annotating.

## Text type

Choose `type` only from `TEXT_TYPES`. Their semantics are:

- `narration`: narrator exposition, action, description, and speech-attribution clauses.
- `dialogue`: directly spoken words, normally marked by quotation or a clearly represented spoken utterance.
- `thought`: explicitly represented internal words or inner monologue.

Quoted material is not automatically dialogue: quotations of documents, signs, titles, or recalled text require context. If dialogue versus thought cannot be resolved, choose the best-supported type and use the corresponding ambiguous-type review reason.

A narration line adjacent to dialogue remains a separate narration segment even when it identifies the speaker.

## Style

Default to `style: null`. If explicit source evidence justifies style, use only fields from `STYLE_FIELDS`, and use only a value listed for that field in `STYLE_VALUES`. These constants—not prose examples and not renderer/provider mappings—are authoritative. Never invent a short English value or treat `render/styles.yaml` as an annotation vocabulary extension.

Examples of explicit evidence:

- “他紧张地说” may justify the canonical nervous emotion value.
- “她低声说” may justify the canonical low volume value.
- “他小声耳语” may justify the canonical whisper delivery value.
- “她笑道” may justify the canonical laugh vocal action when the laughter is part of delivery.

Do not infer style from punctuation alone. Do not carry a style into later speech unless the source continues to state it. Unspecified fields should be present with `null` when a style mapping is used.

## Scenes

Keep one scene while an event or conversation proceeds continuously, even if paragraphs shift focus among participants. Split when there is a clear jump to a new independent event, timeline, narrative thread, or disconnected conversation.

A chapter boundary does not force a scene boundary. For a cross-chapter scene, use one scene with ordered line entries for both chapters.

Scene summaries should be short factual descriptions grounded in the text. Do not include analysis or hidden metadata.

## Review

Choose the primary unresolved problem from `REVIEW_REASONS`; do not create a free-form reason. Split segments if different lines need different review reasons. The unknown system name should normally carry review. A new but clearly named character is not uncertain merely because voices are not configured yet.
