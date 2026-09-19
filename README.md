# Novel TTS tools

将小说 TXT 预处理为可由 LLM 标记和校验的语义数据，并通过独立 renderer 生成带精确时间轴的 TTS 音频。

## 安装

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

## 快速开始

```bash
novel-tts init books/my-book
# 将纯数字章节文件放入 books/my-book/source/，例如 001.txt
novel-tts preprocess books/my-book
novel-tts status books/my-book
```

使用项目 Skill 逐章标记：

```text
/skill:novel-tts-annotator 标记 books/my-book 的 001 章
```

标记后执行：

```bash
novel-tts validate books/my-book
novel-tts review books/my-book
```

使用独立 Skill 配置 renderer；仅配置和 dry-run，不会自动调用付费 API：

```text
/skill:novel-tts-renderer 为 books/my-book 配置 MiMo preset
```

仓库内的 `books/example-book/` 提供了一份完整的双章节《孔乙己》示例，包含场景划分、人物分级、显式说话风格和 MiMo preset 渲染配置：

```bash
novel-tts validate books/example-book
novel-tts review books/example-book
```

## 数据约定

```text
books/my-book/
├── source/          # 原始正文，只读
├── processed/       # 拆分引语并添加章节内行号
├── annotations/     # 每章 segment 标记
├── persons.yaml     # 人物标准名称、别名和角色
├── scenes.yaml      # 全书线性场景
└── voices.yaml      # 可选的旧版 reference_id 映射
```

`persons.yaml` 使用列表保存人物标准名称、别名和角色：

```yaml
persons:
  - name: 小明
    aliases:
      - 明明
    role: main
```

`NARRATOR` 和 `UNKNOWN` 是保留名称，不写入 `persons.yaml`。

`scenes.yaml` 是行号到场景的唯一来源。每个场景在 `line` 中声明一个或多个章节行范围；标注文件只记录 `chapter`、segment 的 `line`、人物、类型、风格和审核状态，不再写入 `scene_id`。程序根据章节和完整行范围从 `scenes.yaml` 推导场景；跨越场景边界的 segment 会被校验拒绝。annotation YAML 的结构规范见 [`docs/annotation.schema.yaml`](docs/annotation.schema.yaml)；词汇仍由 `src/novel_tts/annotation_schema.yaml` 提供。

`source/*.txt` 文件名必须是纯数字。排序按其数值进行；`001.txt` 与 `1.txt` 会被视为重复章节。

预处理将每个非空物理行视为一个原始段落，拆分常见中文引号、直角引号及英文双引号。原始字符、引号和标点保持不变；输出采用 `行号-正文` 格式。

## 命令

```text
novel-tts init BOOK
novel-tts status BOOK
novel-tts preprocess BOOK [--chapter 003]
novel-tts validate BOOK [--chapter 003] [--format text|json]
novel-tts fill-annotations BOOK [--chapter 003]
novel-tts review BOOK
```

校验器检查行号覆盖、segment 重叠、人物引用、scene 范围及顺序、style 字段和 review 标记。命令在存在结构错误时返回非零状态。

Annotator 可以阅读全文，但只把明确的 dialogue、thought 或需要保留审核信息的 narration 写入 annotation；普通未覆盖行由 `novel-tts fill-annotations` 统一补成 `NARRATOR`/`narration`。该命令会按 `scenes.yaml` 的 `line` 范围切分生成 segment，并拒绝重叠、越界和跨场景 segment。annotation 中的 `style` 可以省略；省略与 `style: null` 等价。若写入 style mapping，至少要有一个明确的非 null 值，不能使用空 mapping 或嵌套 null。`scene_id` 不写入 annotation，由程序从章节和行号推导。

## Render 层

完整配置说明见 [Render configuration](docs/render-configuration.md)，模型和供应商字段见 [Renderer providers and models](docs/render-providers.md)。

Render 配置与标记数据隔离，位于每本书的 `render/` 目录：

```text
render/
├── config.yaml              # 模型 profile、输出和审核策略
├── styles.yaml              # 通用 style 到模型控制指令的覆盖映射
├── voices.yaml              # 可用的多模型音色来源目录
├── voice_used.yaml          # 默认 profile 与逐人物声音覆盖
├── cache/                   # 生成缓存，不提交
├── manifests/               # 可复现清单，不提交
└── output/                  # segment、scene、chapter 和全书音频，不提交
```

Renderer 不写入 `processed/`、`annotations/`、`persons.yaml`、`scenes.yaml` 或根目录的 `voices.yaml`。`render/voices.yaml` 只保存可用来源，每个来源明确引用一个 profile：

```yaml
voices:
  林冲:
    fish-main:
      profile: fish-s2-pro
      kind: saved_reference
      reference_id: fish-lin-chong
    mimo-preset:
      profile: mimo-preset
      kind: preset
      voice: 白桦
```

实际选择单独放在 `render/voice_used.yaml`：

```yaml
default_profile: fish-s2-pro
voices:
  林冲: mimo-preset
```

没有人物覆盖时，renderer 会选择该人物在 `default_profile` 下唯一的来源；人物覆盖值是其 `voices.yaml` 中的来源名称。同一个人物可以在同一 profile 下保存多个来源，但此时必须通过人物覆盖消除歧义。命令行 `--profile` 会强制所有人物使用指定 profile，并忽略人物覆盖。存在人物覆盖时，输出目录会带有选择配置摘要，避免不同 mixed 配置互相覆盖。

模型能力按具体 model 校验，而不是只按供应商判断。当前注册了 Fish Audio `s2-pro`/`s2.1-pro` 和 MiMo 的 preset、voicedesign、voiceclone 三类模型。声音模式或流式模式不兼容时会在付费请求前失败，不会静默降级。

完成拼接后会按实际 PCM frame 生成 `timeline.json`、SRT 和 WebVTT。全书、章节和场景 timeline 分别使用对应音频的相对时间；章节和场景文件还会记录全书绝对时间。插入的 segment、scene 和 chapter 静音也包含在时间轴中。过长 segment 会按 `execution.max_chars_per_request` 在句子边界切成多个请求；cache key 包含标准化输出参数。

每次运行会在输出目录的 `snapshots/` 中保存 config、声音选择、style、人物、场景、annotations、processed 和 source 输入，并记录 SHA-256。默认只有所有计划任务成功后才拼接成品；`--allow-partial` 才允许显式生成不完整音频。

```bash
# 查看已知模型能力
novel-tts render capabilities

# 检查配置；不会调用 API
novel-tts render validate-config books/my-book --profile fish-s2-pro

# 显示任务数、字符数和缓存命中；不会调用 API
novel-tts render plan books/my-book --profile mimo-preset

# 执行与断点缓存；安全解析 .env，不覆盖已存在的环境变量
novel-tts render run books/my-book --profile fish-s2-pro --env-file .env
novel-tts render run books/my-book --profile mimo-preset --env-file .env

# 仅用现有 segment WAV 重新拼接
novel-tts render assemble books/my-book --profile fish-s2-pro
novel-tts render status books/my-book --profile fish-s2-pro
```

渲染依赖系统中的 `ffmpeg`。默认遇到 `review: true` 或 `UNKNOWN` 时阻止 API 请求；`--allow-review` 只放行已配置说话人的审核项，不会自动为 `UNKNOWN` 选择声音。HTTP 连接失败和明确可重试状态会按配置重试；读取超时等结果不确定的错误不会自动重试，以免重复产生付费请求。manifest 会记录 request ID、尝试次数和耗时。

## 开发检查

```bash
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest
```

自动修复和格式化：

```bash
uv run --extra dev ruff check . --fix
uv run --extra dev ruff format .
```
