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

## annotations/001.yaml

```yaml
chapter: 1
segments:
  - line: 1-2
    name: NARRATOR
    type: narration
    style: null
    scene_id: S0001
  - line: 3
    name: 小明
    type: dialogue
    style:
      emotion: nervous
      delivery: null
      volume: low
      pace: null
      vocal_action_before: null
      vocal_action_after: null
    scene_id: S0001
  - line: 4
    name: EXTRA
    type: dialogue
    style: null
    scene_id: S0001
  - line: 5
    name: UNKNOWN
    type: dialogue
    style: null
    scene_id: S0001
    review: true
    review_reason: ambiguous_speaker
```

`line` is an integer for one line and `start-end` for a consecutive range. It is never a list in an annotation segment.

## Shared narrator/extra voice

When root `voices.yaml` already contains a narrator binding, copy it exactly:

```yaml
NARRATOR:
  reference_id: narrator
EXTRA:
  reference_id: narrator
```

For an existing render-specific voice file, likewise duplicate the complete specification rather than choosing a new voice:

```yaml
NARRATOR:
  kind: preset
  voice: 冰糖
EXTRA:
  kind: preset
  voice: 冰糖
```
