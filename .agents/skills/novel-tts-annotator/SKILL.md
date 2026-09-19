---
name: novel-tts-annotator
description: Annotates preprocessed Chinese novel chapters with sparse provider-neutral speaker, thought, and explicit reading-style semantics; updates annotations/*.yaml and persons.yaml, then validates them. Use when asked to mark, annotate, continue, inspect, or correct a novel under books/ for the novel TTS workflow.
compatibility: Requires the novel-tts project CLI and its standard book directory layout.
---

# Novel TTS Annotator

Annotate chapters in numeric order. Never alter `source/*.txt` or `processed/*.txt`, and never read or modify render configuration while doing semantic annotation.

## Start with one bounded context command

For chapter `<C>`, run:

```bash
novel-tts agent-context <book> <C>
```

This is the default source of annotation mode, system names, canonical style identifiers, people, aliases, previous-chapter tail, complete current processed chapter, and existing sparse annotation. Do not separately load schema, scenes, render files, voices, cache, manifests, or unrelated chapters.

If processed text is missing, run:

```bash
novel-tts preprocess <book> --chapter <C>
```

Read the complete `[current]` section before assigning speakers. Preserve confirmed existing choices unless they violate the current contract or the user requests re-annotation.

## Write only sparse semantics

Write `<book>/annotations/<C>.yaml` with a root `segments` list.

- Ordinary narration is uncovered and must not be written.
- An explicit segment defaults to `dialogue`; omit `type: dialogue`.
- Use `type: thought` only when agent-context reports thought mode.
- Write explicit `NARRATOR/narration` only when it carries a style override.
- Omit absent style and false review fields.
- Use integer lines or one consecutive `start-end` range. Split non-contiguous lines.
- Never copy正文, chapter, scene ID, role, review reason, voice, provider, or model data into annotation YAML.

Example:

```yaml
segments:
  - line: 7
    name: EXTRA_MALE
  - line: 9
    name: 孔乙己
  - line: 18
    name: 孔乙己
    type: thought
    style:
      emotion: nervous
  - line: 35
    name: UNKNOWN
    review: true
```

## Speaker decisions

Use this evidence order:

1. explicit speech attribution;
2. unambiguous turns in a continuing exchange;
3. an action or form of address that uniquely identifies the speaker;
4. current chapter context;
5. the previous-chapter tail when needed.

Do not decide from personality impressions, gender stereotypes, assumed habits, or unsupported plot guesses.

Use canonical names from `[persons]`, never aliases. Add a person to `persons.yaml` only when the character needs a stable independent identity. Add only genuine textual name variants as aliases.

System-name semantics:

- `NARRATOR`: default narration;
- `UNKNOWN`: speaker is unresolved; always add `review: true`;
- `EXTRA`: resolved incidental speaker without reliable gender classification;
- `EXTRA_MALE`: resolved incidental male speaker with textual/contextual support;
- `EXTRA_FEMALE`: resolved incidental female speaker with textual/contextual support.

Do not add system names to `persons.yaml`. Do not replace an unresolved possible recurring character with EXTRA merely to avoid UNKNOWN.

## Text type and style

Quoted text is not automatically dialogue; documents, signs, titles, and recalled text require context. First-person exposition remains narrator speech, while explicitly represented internal words may be thought when the book enables it.

Use only style identifiers printed by agent-context. Mark style only when the正文 explicitly supplies the reading information. Do not infer style from punctuation, carry it from a previous sentence, or invent a new value.

Narration, dialogue, and thought use the same style structure.

## Finish

Run:

```bash
novel-tts validate <book> --chapter <C>
novel-tts review <book>
```

Repair structural errors, but keep honest `UNKNOWN + review:true` rather than guessing. Report remaining review items to the user. `scenes.yaml` is optional metadata and is not part of the annotation decision workflow.
