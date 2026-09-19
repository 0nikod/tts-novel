# Sparse annotation

本文定义 preprocessing 之后的语义数据、Agent 标注工作流和 validation 规则。Annotation 永久保持与声音、模型和 API 解耦。

## 数据边界

人工维护：

```text
source/*.txt
annotations/*.yaml
persons.yaml
book.yaml          # 可选
scenes.yaml        # 可选元数据
```

派生数据：

```text
processed/*.txt
runtime effective segments
```

`annotations/*.yaml` 只能保存：

- 连续 processed line range；
- canonical speaker name；
- 文本类型；
- 正文明示的 reading style；
- speaker 尚未解决时的 review 状态。

禁止保存 chapter、scene ID、人物等级、review reason、正文副本、speaker/reference ID、provider、model、API 参数、音频路径和 cache key。章节编号只由文件名确定，例如 `annotations/003.yaml` 对应 `processed/003.txt`。

## Preprocessing contract

```bash
novel-tts preprocess BOOK
novel-tts preprocess BOOK --chapter 003
```

Preprocessing：

1. 读取按数字命名的 `source/*.txt`；
2. 跳过空物理行；
3. 按项目既有引号规则拆分正文和直接引语；
4. 保留原始字符、标点和引号；
5. 从 1 开始连续编号并写入 `processed/*.txt`。

```text
1-正文
2-“对话”
3-正文
```

Agent 和 annotation 只引用 processed line，不把正文复制进 YAML。修改 source 后必须重新 preprocess，并重新检查对应 annotation range。

## Canonical sparse format

最小文件：

```yaml
segments: []
```

典型文件：

```yaml
segments:
  - line: 7
    name: EXTRA_MALE

  - line: 9
    name: 孔乙己

  - line: 11
    name: EXTRA
    style:
      direction: 提高音量喊话，语速急促。
      tags_before: [深呼吸]

  - line: 18
    name: 孔乙己
    type: thought

  - line: 35
    name: UNKNOWN
    review: true

  - line: 40-42
    name: NARRATOR
    type: narration
    style:
      direction: 放慢语速，保持克制。
      tags_after: [叹气]
```

Canonical YAML 省略所有默认值：

- 普通 narration 不创建 segment；
- 显式 segment 缺少 `type` 时为 `dialogue`；
- 无 style 时省略 `style`，不写 `style: null` 或空 mapping；
- `review: false` 省略；
- 普通 dialogue 省略 `type: dialogue`。

`line` 只支持正整数或连续的 `start-end` range：

```yaml
line: 3
line: 3-5
```

非连续 line list 必须拆成多个 segment。Segment 必须按行号严格递增、不得重叠或越过 processed 章节末尾。

## Runtime materialization

未被显式 segment 覆盖的每一行在运行时解释为：

```text
name   = NARRATOR
type   = narration
style  = null
review = false
```

`materialize_annotation()` 扫描 sparse segment、补齐 gap，并合并相邻且语义完全相同的 effective segment。Materialized 数据只供 `inspect` 和 renderer 使用，绝不写回 `annotations/`。

检查 effective 结果：

```bash
novel-tts inspect BOOK --chapter 003
novel-tts inspect BOOK --chapter 003 --format yaml
novel-tts inspect BOOK --chapter 003 --format json
```

## Annotation mode

缺少 `book.yaml` 或 annotation 设置时默认为 `dialogue` mode：

```text
narration
dialogue
```

需要明确区分内部独白时启用 thought mode：

```yaml
# book.yaml
annotation:
  mode: thought
```

Thought mode 允许：

```text
narration
dialogue
thought
```

只有 thought 需要显式 `type: thought`。Dialogue mode 中出现 thought 会导致 validation error。

Narration、dialogue、thought 共用相同 style 结构。显式 narration segment 只用于覆盖默认 narration，例如提供有明确证据的自然语言 `direction`。

## Speaker 与 persons

系统名称：

| 名称 | 语义 |
|---|---|
| `NARRATOR` | 默认 narration speaker |
| `UNKNOWN` | speaker 无法可靠确定，必须人工复核 |
| `EXTRA` | 已确定为临时 speaker，但没有可靠性别分类 |
| `EXTRA_MALE` | 正文或可靠上下文明示的男性临时 speaker |
| `EXTRA_FEMALE` | 正文或可靠上下文明示的女性临时 speaker |

`UNKNOWN` 是尚未完成的判断；`EXTRA*` 是已经完成、但不需要独立人物身份的判断。不得为了消除 UNKNOWN 而随意使用 EXTRA，也不得仅凭刻板印象选择 EXTRA_MALE 或 EXTRA_FEMALE。

`persons.yaml` 只保存需要长期维持独立身份的人物和真实 alias：

```yaml
persons:
  - name: 小明
    aliases:
      - 明明

  - name: 小红
    aliases: []
```

Annotation 必须使用 canonical name，不能使用 alias。所有系统名称都由程序预定义，不得加入 person name 或 alias。

Speaker 判断证据顺序：

1. 明确的发言归属；
2. 连续对话中明确的轮次关系；
3. 唯一确定 speaker 的动作或称呼；
4. 当前章节上下文；
5. 必要时使用前章末尾上下文。

不得仅根据性格印象、性别刻板印象、假定行为习惯或缺乏文本依据的剧情推测确定 speaker。

## Review

第一版 review 只表示 speaker 未解决：

```yaml
segments:
  - line: 23
    name: UNKNOWN
    review: true
```

约束：

- `UNKNOWN` 必须有 `review: true`；
- 其他 speaker 不得使用 `review: true`；
- 不保存 review reason；
- renderer 在存在 UNKNOWN 时停止。

列出所有 review item 和对应正文：

```bash
novel-tts review BOOK
```

## Reading style

Style 使用轻量、开放、provider-neutral 的自然语言结构：

```yaml
style:
  direction: |-
    声音压低，略显迟疑，语速稍慢。
    前半句保持镇定，后半句逐渐流露疲惫。
  tags_before: [紧张, 深呼吸]
  tags_after: [苦笑]
```

只支持三个字段：

| 字段 | 含义 |
|---|---|
| `direction` | 作用于整个 semantic segment 的非空自然语言表演指导 |
| `tags_before` | segment 开头的有序、非空自由文本标签列表 |
| `tags_after` | segment 结尾的有序、非空自由文本标签列表 |

Annotation 只保存 `深呼吸`、`苦笑` 这样的语义文字，不保存 MiMo 的 `()` 或 Fish/ElevenLabs 的 `[]` 等 provider 语法。Renderer adapter 负责包装。

Style 原则：

- **没有明确的正文证据或可靠上下文证据时，完全不写 style**；
- 不从标点、人物性格、偏好的声线或想象中的演出单独推断；
- 不因上一句有 style 就自动延续；
- 使用证据支持的最短 direction 和最少标签；
- 不为普通句子例行添加导演指令；
- 一个 style 对象至少包含一个非空字段，标签不得为空或重复。

自然语言 direction 是主要表示。不提供 `emotion`、`speed`、`pitch` 等结构化 provider 参数，也不承诺兼容只接受这类参数的 TTS。

## Agent workflow

每章开始时运行一次：

```bash
novel-tts agent-context BOOK 003
```

默认输出：

- annotation mode 和默认行为；
- system names；
- style identifiers；
- persons 与 aliases；
- 前一 processed 章节末尾 20 行；
- 当前 processed 章节全文；
- 当前已有 sparse annotation。

可选参数：

```bash
novel-tts agent-context BOOK 003 --previous-lines 30
novel-tts agent-context BOOK 003 --no-existing
novel-tts agent-context BOOK 003 --format json
```

该命令不读取 scenes、render config、voices、cache、manifest 或其他章节全文。Agent 应读完完整 current chapter 后再写 segment，发现稳定新人物或真实 alias 时同步更新 `persons.yaml`。

完成后运行：

```bash
novel-tts validate BOOK --chapter 003
novel-tts review BOOK
```

保留诚实的 UNKNOWN，不要为了通过 validation 猜测 speaker。

## Optional scenes

`scenes.yaml` 是可选 metadata：

```yaml
scenes:
  - id: S0001
    line: '001:1-38'
    summary: 小明出门并遇到小红

  - id: S0002
    line:
      - '001:39-86'
      - '002:1-16'
    summary: 两人继续交谈
```

Annotation 不保存 scene ID，也不要求 segment 位于单一 scene。Renderer 如需 scene gap，会在运行时按 scene 边界拆分 job，而不修改 canonical segment。

Scene 文件存在时只检查自身：引用章节和 line 是否存在、range 是否越界、scene ID 是否重复、range 是否重叠。Scene ID 不要求连续。删除 scenes 不会阻止 annotation validation 或基本 render plan。

## Validation contract

`novel-tts validate` 分别检查 annotation 数据和存在的 scene metadata。

Annotation 层检查：

- processed 文件存在、格式正确、行号从 1 连续；
- persons 和 aliases 唯一且不占用系统名称；
- annotation YAML 只有受支持字段；
- segment range 有效、有序、不重叠、不越界；
- name 是 canonical person 或 system name；
- type 符合本书 annotation mode；
- style 只包含 direction、tags_before、tags_after，且内容非空；
- UNKNOWN/review 约束。

不检查 full coverage、chapter 字段或 scene membership。

## Generated schema

`docs/annotation.schema.yaml` 是从 `src/novel_tts/annotation_schema.py` 生成的 JSON Schema YAML，不得手工修改：

```bash
uv run python -m novel_tts.schema_codegen
# 或
novel-tts schema annotation --output docs/annotation.schema.yaml
```

`test_generated_annotation_schema_is_current` 会比较生成结果与仓库文件。修改 mode、system name 或 style 结构时，应修改 Python source of truth、重新生成 schema，再运行完整测试。
