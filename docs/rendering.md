# Private custom TTS rendering

Renderer 只面向一个私有 custom TTS backend。它消费 effective semantic segments、每书 casting 和可选 scene/style metadata；不会把模型信息反向写入 annotation。

## Ownership 与目录

人工维护：

```text
render/config.yaml
render/voices.yaml
render/voice_used.yaml
render/styles.yaml       # 可选
```

运行时生成：

```text
render/cache/
render/manifests/
render/output/
```

推荐的 `render/.gitignore`：

```gitignore
cache/
manifests/
output/
```

完整结构：

```text
render/
├── config.yaml
├── voices.yaml
├── voice_used.yaml
├── styles.yaml
├── cache/                    # normalized job WAV
├── manifests/
│   └── latest.json
└── output/
    ├── segments/<chapter>/   # 每个 RenderJob 的 WAV
    ├── chapters/<chapter>.wav
    ├── book.wav
    └── book.<final_format>   # final_format 不是 wav 时
```

Chapter-only run 只更新该章的 segment 和 chapter WAV，不生成全书音频。

## Render workflow

所有免费检查应在 API 调用前完成：

```bash
novel-tts validate BOOK
novel-tts render validate BOOK
novel-tts render plan BOOK
```

只规划一章：

```bash
novel-tts render plan BOOK --chapter 003
```

`validate` 检查 custom backend 配置、voice catalog、casting、style mapping、effective speaker 和 annotation 前置条件。`plan` 进一步 materialize annotation、切 scene/range、切 request chunk、编译 style 并计算 cache hit/miss，但不会读取 API key 或发起网络请求。

只有显式执行以下命令才允许调用私有 API：

```bash
novel-tts render run BOOK --env-file .env
novel-tts render run BOOK --chapter 003 --env-file .env
```

重新使用现有 segment 拼接，不调用 API：

```bash
novel-tts render assemble BOOK
novel-tts render assemble BOOK --chapter 003
novel-tts render status BOOK
```

## `config.yaml`

```yaml
endpoint: http://127.0.0.1:8000/v1/tts
model: custom-model
api_key_env: TTS_API_KEY
concurrency: 2
timeout_seconds: 120
retries: 2

output:
  sample_rate: 24000
  channels: 1
  final_format: mp3

assembly:
  dialogue_gap_ms: 180
  narration_gap_ms: 260
  scene_gap_ms: 800
  chapter_gap_ms: 1500

execution:
  max_chars_per_request: 200
```

字段：

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `endpoint` | 必填 | 私有 TTS HTTP endpoint |
| `model` | 必填 | 参与 request 和 cache key 的模型标识 |
| `api_key_env` | 必填 | 保存 API key 的环境变量名 |
| `concurrency` | `2` | 同时执行的 job 数 |
| `timeout_seconds` | `120` | 单次 HTTP request timeout |
| `retries` | `2` | 可重试错误的额外尝试次数 |
| `output.sample_rate` | `24000` | cache 与拼接 WAV 的采样率 |
| `output.channels` | `1` | cache 与拼接 WAV 的声道数 |
| `output.final_format` | `mp3` | `wav`、`mp3`、`opus` 或 `m4a` |
| `assembly.dialogue_gap_ms` | `180` | dialogue job 后的 gap |
| `assembly.narration_gap_ms` | `260` | narration/thought job 后的 gap |
| `assembly.scene_gap_ms` | `800` | scene 变化时的 gap |
| `assembly.chapter_gap_ms` | `1500` | chapter 变化时的 gap |
| `execution.max_chars_per_request` | `200` | 单个 request 的文本上限 |

实现还接受 `assembly.chunk_gap_ms`，默认 `0`，用于同一 semantic segment 被拆成多个 request 时的内部 gap。

API key 只从环境变量读取，不写入 YAML、manifest 或输出。Plan 不要求 key 存在；run 也只有遇到 cache miss 时才需要 key。

## Voice catalog

`voices.yaml` 保存当前可用的音源，而不是人物 selection：

```yaml
voices:
  narrator-main:
    reference_id: narrator-001

  male-old-01:
    reference_id: male-old-003
    reference_text: 与参考音频匹配的文本
```

第一层 key 是本地稳定 voice ID。其下字段由 private backend 定义，renderer 将它们作为 voice 参数发送。旧 provider framework 的 `profile`、`provider` 和 `kind` 字段无效。

一个 catalog voice 可以供多个角色复用。更换 reference 数据只需修改 catalog 或 casting，不需要重做 annotation。

## Casting

`voice_used.yaml` 保存 canonical speaker 到 voice ID 的 selection：

```yaml
voices:
  NARRATOR: narrator-main
  小明: male-old-01
  小红: female-young-01
  EXTRA: narrator-main
  EXTRA_MALE: male-young-01
  EXTRA_FEMALE: female-young-01
```

正式 render 前要求：

- 每个 effective speaker 都有 selection；
- selection 引用的 voice ID 存在；
- speaker 是 person 或 system name；
- `UNKNOWN` 不存在于 annotation；
- `UNKNOWN` 不得出现在 `voice_used.yaml`。

缺少 casting 时 plan 会一次列出所有名称：

```text
Missing voices:
  小明
  EXTRA_FEMALE
```

## Style compiler

Annotation 保存 provider-neutral semantic style。默认 compiler 将字段和值原样交给 private API：

```yaml
emotion: nervous
volume: low
```

`render/styles.yaml` 可以覆盖某个 canonical value 的 private representation：

```yaml
emotion:
  nervous: tense
pace:
  slow: 0.8
```

默认映射足够时写：

```yaml
{}
```

覆盖的 field/value 必须已存在于 annotation vocabulary，但输出值可以是 private model 需要的 YAML 值。改变模型映射时修改 `renderer/style.py` 或 `styles.yaml`，不修改历史 annotation。

长 segment 切块时，`vocal_action_before` 只保留在第一块，`vocal_action_after` 只保留在最后一块。

## Planner 与 RenderJob

Planner 按以下顺序工作：

1. 验证 processed、persons、sparse annotation 和存在的 scenes；
2. runtime materialize 所有默认 narration；
3. 阻止 UNKNOWN；
4. 加载 `voice_used.yaml` 并解析 catalog voice；
5. 根据可选 scene 边界拆分 runtime range；
6. 按中文/英文句末、次级标点和最终硬切分限制 request 长度；
7. 编译 style；
8. 为每个 chunk 生成 cache key 和 RenderJob。

RenderJob 包含：

```text
id
chapter
line_start / line_end
text
name
text_type
style / compiled_style
voice
chunk_index / chunk_count
cache_key
scene_id             # 可选 runtime 字段
```

Scene 拆分和 request chunk 都不会修改 canonical annotation。

## Custom API contract

所有 private API 特有逻辑集中在 `src/novel_tts/renderer/custom_tts.py`。当前 request 使用 JSON：

```json
{
  "model": "custom-model",
  "text": "朗读文本",
  "voice": {
    "id": "male-old-01",
    "reference_id": "male-old-003"
  },
  "style": {
    "emotion": "nervous"
  }
}
```

认证头：

```text
Authorization: Bearer <API_KEY>
Accept: audio/*, application/json
```

支持两类成功响应：

1. 直接返回带 audio content type 的音频 body；
2. 返回 JSON：

```json
{
  "audio_base64": "...",
  "format": "wav"
}
```

JSON 中也接受 `audio` 作为 base64 字段名。缺少 format 时按 WAV 处理。

以下情况按 `retries` 重试：

- timeout；
- connection、read/write 或 protocol transport error；
- HTTP 429；
- 任意 HTTP 5xx。

普通 HTTP 4xx 和成功响应中的 API/data error 不重试。若私有接口协议不同，只修改 `custom_tts.py`；planner、annotation 和 voice selection 不理解接口字段。

## Cache

每个 cache 文件是按 output 配置规范化后的 PCM s16 WAV：

```text
render/cache/<sha256>.wav
```

Cache key 至少包含：

- endpoint 和 model；
- request text；
- voice ID 及全部 voice 参数；
- compiled style；
- output sample rate、channels 和 final format；
- cache schema version。

正文、casting、reference、style、模型或影响音频的输出参数变化会生成新 key。Cache hit 会先验证 WAV 结构，然后直接复制到 output segment，不调用 API。项目不迁移旧 renderer cache。

## Audio 与 assembly

Provider 响应先由 ffmpeg 规范化为目标 sample rate、channel count 和 PCM s16 WAV，再进入 cache。执行 synthesis 或最终非 WAV 转码前，系统中必须可用 `ffmpeg`。

Gap 优先级：

1. 同一 segment 的内部 chunk gap；
2. chapter gap；
3. 存在 scene metadata 时的 scene gap；
4. dialogue 或 narration/thought gap。

只有全部计划 job 成功才会生成最终 chapter/book 音频。任何失败都会：

- 标记 manifest job 为 failed；
- 删除可能陈旧的对应最终拼接文件；
- 保留已成功 cache 和 segment WAV；
- 阻止不完整 assembly。

修复配置或 API 后重新运行即可复用成功 cache。没有 partial assembly 模式。

## Manifest

最近一次 run 写入：

```text
render/manifests/latest.json
```

记录内容包括：

- 开始/结束时间和 model；
- whole-book 或 chapter filter；
- config、voices、voice selection、styles、processed 和 annotation hash；
- job ID、chapter/range、speaker、type、voice、style 和 cache key；
- cache hit/miss、request ID、attempts、elapsed time；
- status、duration、output file 和错误；
- completed/failed count 与 assembly 状态。

Manifest 不复制 source、processed、annotation 或 render 配置 snapshot。

## 常见阻塞

### `UNKNOWN speaker cannot be rendered`

运行 `novel-tts review BOOK`，回到 annotation workflow 解决 speaker。不要给 UNKNOWN 配置 voice。

### `Missing voices`

在 `voice_used.yaml` 中为列出的 effective speaker 选择 catalog voice。

### `references missing voice`

修正 `voice_used.yaml` 中不存在或拼写错误的 voice ID。

### `environment variable ... is not set`

通过环境或 `--env-file` 提供 `api_key_env` 指定的变量。不要把 secret 写入 YAML。

### `planned segment(s) are missing`

`render assemble` 只使用已经生成的 segment。先运行 `render run` 补齐缺失 job。

### ffmpeg error

确认 ffmpeg 已安装，并检查 private API 返回的 format 与实际音频编码是否一致。
