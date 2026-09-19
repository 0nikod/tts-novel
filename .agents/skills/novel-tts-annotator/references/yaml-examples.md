# Canonical file examples

## persons.yaml

```yaml
persons:
  - name: 小明
    aliases:
      - 明明
    role: main
  - name: 小红
    aliases: []
    role: secondary
  - name: EXTRA
    aliases: []
    role: minor
```

`NARRATOR` and `UNKNOWN` are reserved and are not declared here. All incidental minor characters use the one `EXTRA` entry; do not list their individual names as aliases.

## scenes.yaml

```yaml
scenes:
  - id: S0001
    line: '001:1-38'
    summary: 小明出门并遇到小红
  - id: S0002
    line:
      - '001:39-86'
      - '002:1-16'
    summary: 小明与小红继续交谈
```

Quote scene ranges so YAML always treats them as strings.

`docs/annotation.schema.yaml` defines the annotation document shape. `src/novel_tts/annotation_schema.yaml` defines canonical vocabulary. `scenes.yaml` is the source of truth for mapping an annotation chapter and complete line range to a scene. Annotation segments do not contain `scene_id`.

## annotations/001.yaml — sparse input

The annotator may write only explicit dialogue/thought segments. `style` is optional: omit it when there is no explicit style evidence. The completion command later adds ordinary narration.

```yaml
# chapter: numeric source chapter; this is not a scene identifier.
chapter: 1
segments:
  # Only a deliberately modeled spoken line is written here.
  - line: 3
    name: 小明
    type: dialogue
    # style is omitted because no explicit style is present.
```

Run `novel-tts fill-annotations BOOK --chapter 001` to fill the uncovered lines.

## annotations/001.yaml — completed output

```yaml
# `scene_id` is intentionally absent; scenes.yaml owns line-to-scene mapping.
chapter: 1
segments:
  - line: 1-2
    name: NARRATOR
    type: narration
    # style may be omitted when it is null.
  - line: 3
    name: 小明
    type: dialogue
    style:
      emotion: nervous
      volume: low
  - line: 4
    name: EXTRA
    type: dialogue
    style: null
  - line: 5
    name: UNKNOWN
    type: dialogue
    style: null
    review: true
    review_reason: ambiguous_speaker
```

`line` is an integer and `start-end` is a consecutive range. It is never a list in an annotation segment; range ordering is checked by the program. `name` is a canonical person or reserved system name; `type` is one of `narration`, `dialogue`, or `thought`; `review` is optional and defaults to false; `review_reason` is required only when `review: true`. `style` may be omitted or be `null`; when it is a mapping, include only canonical fields with explicit non-null values. `scene_id` must not be written.
