# Novel TTS annotation tools

将小说 TXT 预处理为可由 LLM 标记并进行结构校验的数据。本项目暂不包含 TTS renderer。

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

仓库内的 `books/example-book/` 提供了一份完整的双章节《水浒传》节选示例，包含多场景划分、人物别名、内心独白、显式说话风格以及待人工审核的说话人：

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
└── voices.yaml      # name 到 reference_id 的映射
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

`source/*.txt` 文件名必须是纯数字。排序按其数值进行；`001.txt` 与 `1.txt` 会被视为重复章节。

预处理将每个非空物理行视为一个原始段落，拆分常见中文引号、直角引号及英文双引号。原始字符、引号和标点保持不变；输出采用 `行号-正文` 格式。

## 命令

```text
novel-tts init BOOK
novel-tts status BOOK
novel-tts preprocess BOOK [--chapter 003]
novel-tts validate BOOK [--chapter 003] [--format text|json]
novel-tts review BOOK
```

校验器检查行号覆盖、segment 重叠、人物引用、scene 范围及顺序、style 字段和 review 标记。命令在存在结构错误时返回非零状态。

## Render 层

Render 配置与标记数据隔离，位于每本书的 `render/` 目录：

```text
render/
├── config.yaml              # 模型 profile、输出和审核策略
├── styles.yaml              # 通用 style 到模型控制指令的覆盖映射
├── voices/                  # 模型专属音色配置
├── cache/                   # 生成缓存，不提交
├── manifests/               # 可复现清单，不提交
└── output/                  # segment、scene、chapter 和全书音频，不提交
```

Renderer 不写入 `processed/`、`annotations/`、`persons.yaml`、`scenes.yaml` 或根目录的 `voices.yaml`。Fish profile 可以继续只读使用原有 `voices.yaml`；MiMo 的预置、文字设计和克隆音色分别使用 render 专属文件。

模型能力按具体 model 校验，而不是只按供应商判断。当前注册了 Fish Audio `s2-pro`/`s2.1-pro` 和 MiMo 的 preset、voicedesign、voiceclone 三类模型。声音模式或流式模式不兼容时会在付费请求前失败，不会静默降级。

```bash
# 查看已知模型能力
novel-tts render capabilities

# 检查配置；不会调用 API
novel-tts render validate-config books/my-book --profile fish-s2-pro

# 显示任务数、字符数和缓存命中；不会调用 API
novel-tts render plan books/my-book --profile mimo-preset

# 执行与断点缓存
FISH_AUDIO_API_KEY=... novel-tts render run books/my-book --profile fish-s2-pro
MIMO_API_KEY=... novel-tts render run books/my-book --profile mimo-preset

# 仅用现有 segment WAV 重新拼接
novel-tts render assemble books/my-book --profile fish-s2-pro
novel-tts render status books/my-book --profile fish-s2-pro
```

渲染依赖系统中的 `ffmpeg`。默认遇到 `review: true` 或 `UNKNOWN` 时阻止 API 请求；`--allow-review` 只放行已配置说话人的审核项，不会自动为 `UNKNOWN` 选择声音。

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
