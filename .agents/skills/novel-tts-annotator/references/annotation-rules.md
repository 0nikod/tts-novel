# Annotation decision rules

## Speaker (`name`)

Use the canonical `name` from the `persons` list in `persons.yaml`.

Evidence priority:

1. Explicit speech attribution attached to the quotation.
2. A continuing two-person exchange with an unambiguous turn pattern.
3. Actions or forms of address that uniquely identify the speaker.
4. Broader scene context.

Do not infer a speaker solely from stereotyped personality, gender, or likely behavior. If multiple candidates remain plausible, use `UNKNOWN`, `review: true`, and `ambiguous_speaker`.

Narrative prose normally uses `NARRATOR`. A first-person narrator still uses `NARRATOR` for narration; use the canonical character name only for their direct dialogue or represented thought.

### Narrator-only paratext

When a section is headed or clearly identified as `后记`, `作者后记`, `译者后记`, `作者注`, `译者注`, an editorial note, acknowledgements, or similar non-story material, assign `name: NARRATOR` to every line until that section ends. This override also applies to quoted speech, signatures, names, and attributed remarks inside the section. Preserve the normal `type` decision (`narration`, `dialogue`, or `thought`) based on the textual form; only the speaker name is forced to `NARRATOR`.

Do not add an author, translator, editor, relative, or other person to `persons.yaml` solely because they appear in narrator-only paratext. If the same person independently appears as a character in the story, their story occurrences still follow the normal speaker rules.

## Text type

- `narration`: narrator exposition, action, description, and speech-attribution clauses.
- `dialogue`: directly spoken words, normally marked by quotation or a clearly represented spoken utterance.
- `thought`: explicitly represented internal words or inner monologue.

Quoted material is not automatically dialogue: quotations of documents, signs, titles, or recalled text require context. If dialogue versus thought cannot be resolved, choose the best-supported type and mark `ambiguous_type`.

A narration line adjacent to dialogue remains a separate narration segment even when it identifies the speaker.

## Style

Default to `style: null`. Allowed fields are:

- `emotion`
- `delivery`
- `volume`
- `pace`
- `vocal_action_before`
- `vocal_action_after`

Use a short English value only when the original explicitly states it. Examples:

- “他紧张地说” may justify `emotion: nervous`.
- “她低声说” may justify `volume: low`.
- “他小声耳语” may justify `delivery: whisper`.
- “她笑道” may justify a vocal action when the laughter is part of delivery.

Do not infer style from punctuation alone. Do not carry a style into later speech unless the source continues to state it. Unspecified fields should be present with `null` when a style mapping is used.

## Scenes

Keep one scene while an event or conversation proceeds continuously, even if paragraphs shift focus among participants. Split when there is a clear jump to a new independent event, timeline, narrative thread, or disconnected conversation.

A chapter boundary does not force a scene boundary. For a cross-chapter scene, use one scene with ordered line entries for both chapters.

Scene summaries should be short factual descriptions grounded in the text. Do not include analysis or hidden metadata.

## Review

A review reason identifies the primary unresolved problem. Split segments if different lines need different review reasons. `UNKNOWN` should normally carry review. A new but clearly named character is not uncertain merely because voices are not configured yet.
