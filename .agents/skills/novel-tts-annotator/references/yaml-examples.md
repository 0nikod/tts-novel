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
```

`NARRATOR` and `UNKNOWN` are reserved and are not declared here.

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
    name: UNKNOWN
    type: dialogue
    style: null
    scene_id: S0001
    review: true
    review_reason: ambiguous_speaker
```

`line` is an integer for one line and `start-end` for a consecutive range. It is never a list in an annotation segment.
