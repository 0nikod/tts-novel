# tts-novel

面向个人使用的小说 TTS 工具。项目把**正文、稀疏语义标注、声音选择、运行产物**分开管理，标注永久保持与具体 TTS 模型解耦。

## 快速开始

```bash
uv sync --extra dev
uv run novel-tts init books/my-book

# 将按数字命名的 TXT 放入 books/my-book/source/
uv run novel-tts preprocess books/my-book

# Agent 标注
/skill:novel-tts-annotator 标记 books/my-book 的 001 章

# 检查语义数据
uv run novel-tts validate books/my-book
uv run novel-tts review books/my-book
uv run novel-tts inspect books/my-book --chapter 001

# 编辑 render/voices.yaml 和 render/voice_used.yaml 后进行免费预检
uv run novel-tts render validate books/my-book
uv run novel-tts render plan books/my-book

# 只有此命令会调用所选 TTS provider
uv run novel-tts render run books/my-book --env-file .env
```

## 数据结构

```text
books/<book>/
├── book.yaml                  # 可选：annotation.mode
├── source/*.txt               # 人工维护的原始章节
├── processed/*.txt            # preprocess 派生
├── annotations/*.yaml         # 人工维护的稀疏语义标注
├── persons.yaml               # 人物 canonical identity 与 alias
├── scenes.yaml                # 可选元数据
└── render/
    ├── config.yaml            # target、profiles 与执行配置
    ├── voices.yaml            # 可用音源目录
    ├── voice_used.yaml        # 本书 casting
    ├── cache/                 # 运行数据
    ├── manifests/             # 运行记录
    └── output/                # 音频
```

依赖方向固定为：

```text
source → processed → annotations + persons → effective segments
       → voice selection → provider adapter → cache → audio
```

`scenes.yaml` 是可选增强，不是 annotation 的依赖。

## 稀疏 annotation

普通 narration 不写入 YAML；未被 segment 覆盖的 processed line 在运行时自动成为 `NARRATOR/narration`。显式 segment 默认是 dialogue，所以通常只需要：

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

  - line: 35
    name: UNKNOWN
    review: true
```

chapter 由文件名确定。普通 dialogue 不写 `type`，空 style 不写 `style`。只有 thought 或显式 narration 覆盖需要写 `type`：

```yaml
# book.yaml
annotation:
  mode: thought
```

```yaml
segments:
  - line: 18
    name: 孔乙己
    type: thought
    style:
      direction: 低声、迟疑，后半句逐渐疲惫。
      tags_after: [苦笑]

  - line: 40-42
    name: NARRATOR
    type: narration
    style:
      direction: 放慢语速，保持克制。
```

系统名称为 `NARRATOR`、`UNKNOWN`、`EXTRA`、`EXTRA_MALE`、`EXTRA_FEMALE`，不得写入 `persons.yaml`。`UNKNOWN` 必须使用 `review: true`，并会阻止正式 render。

详细语义见 [docs/annotation.md](docs/annotation.md)。编辑器 schema 位于自动生成的 [docs/annotation.schema.yaml](docs/annotation.schema.yaml)。

## Agent 上下文

一次命令输出当前章节所需的最小上下文：

```bash
uv run novel-tts agent-context books/my-book 003
uv run novel-tts agent-context books/my-book 003 --previous-lines 30
uv run novel-tts agent-context books/my-book 003 --no-existing --format json
```

默认只包含 annotation mode、系统名称、自然语言 style 字段、人物与 alias、前章末尾 20 行、当前 processed 全文和已有 sparse annotation；不会读取 scenes 或 render 配置。

## Multi-provider TTS renderer

Renderer 当前内置 `custom` 和 Xiaomi MiMo V2.5 TTS adapter。`render/config.yaml` 可以声明多个 profile；每个 voice 选择一个 profile，因此同一计划可以混合 provider/model。Annotation 不保存任何模型信息。

`render/voices.yaml` 的 voice ID 表示一个具体可执行音源。省略 `profile` 时使用 `default_profile`：

```yaml
# render/voices.yaml
voices:
  narrator-designed:
    profile: mimo-design
    mode: design
    description: 平静、克制的近距离小说旁白声。
  male-old-preset:
    mode: preset
    voice: 白桦
```

```yaml
# render/voice_used.yaml
voices:
  NARRATOR: narrator-designed
  孔乙己: male-old-preset
  EXTRA: narrator-designed
```

多个人物可以共享声音；禁止为 `UNKNOWN` 配置声音。配置、cache 和拼接规则见 [docs/rendering.md](docs/rendering.md)，Custom/MiMo 协议见 [docs/providers.md](docs/providers.md)。

## 常用命令

```text
novel-tts init BOOK
novel-tts preprocess BOOK [--chapter 003]
novel-tts status BOOK
novel-tts agent-context BOOK 003
novel-tts validate BOOK [--chapter 003]
novel-tts review BOOK
novel-tts inspect BOOK --chapter 003 [--format text|yaml|json]
novel-tts schema annotation [--output PATH]

novel-tts render providers
novel-tts render validate BOOK
novel-tts render plan BOOK [--chapter 003]
novel-tts render run BOOK [--chapter 003] [--env-file .env]
novel-tts render assemble BOOK [--chapter 003]
novel-tts render status BOOK
```

## 开发检查

```bash
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest
```

更新 `src/novel_tts/annotation_schema.py` 后重新生成 schema：

```bash
uv run python -m novel_tts.schema_codegen
```
