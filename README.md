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

## 数据约定

```text
books/my-book/
├── source/          # 原始正文，只读
├── processed/       # 拆分引语并添加章节内行号
├── annotations/     # 每章 segment 标记
├── persons.md       # 人物标准名称、别名和角色
├── scenes.yaml      # 全书线性场景
└── voices.yaml      # name 到 reference_id 的映射
```

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
