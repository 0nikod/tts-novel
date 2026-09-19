# Mixed-profile TTS rendering

Renderer 消费 effective semantic segments、每书 casting 和可选 scene metadata，通过 provider adapter 生成音频。Annotation 始终 provider-neutral；target、profile、model、voice source 和请求参数只属于 `render/`。

当前支持在一个 render plan 中按 speaker 混用不同 profile。例如旁白使用 MiMo voice design，角色使用 preset 或 clone。Provider 协议和 MiMo 配置见 [providers.md](providers.md)。

## Ownership 与目录

人工维护：

```text
render/config.yaml
render/voices.yaml
render/voice_used.yaml
```

运行时生成并由 `render/.gitignore` 忽略：

```text
render/cache/
render/manifests/
render/output/
```

完整结构：

```text
render/
├── config.yaml
├── voices.yaml
├── voice_used.yaml
├── cache/<sha256>.wav
├── manifests/<target>.json
└── output/<target>/
    ├── segments/<chapter>/
    ├── chapters/<chapter>.wav
    ├── book.wav
    └── book.<final_format>
```

`target` 是人工指定的稳定输出名称。修改 casting 后重新运行会更新同一 target；cache key 仍能防止错误复用。若需要保留多个成品版本，应使用不同 target。

Chapter-only run 只更新该章的 segment 和 chapter WAV，不生成全书音频。

## Workflow 与执行门槛

API 调用前完成免费检查：

```bash
novel-tts validate BOOK
novel-tts render providers
novel-tts render validate BOOK
novel-tts render plan BOOK
```

只规划一章：

```bash
novel-tts render plan BOOK --chapter 003
```

`validate` 检查所有 profile、实际使用的 voice、casting、effective speaker 和 annotation。`plan` 进一步 materialize annotation、按 scene/range 和 request 大小切分、按 job profile 编译 style，并报告总计和每个 profile 的 job/字符/cache 数。两者都不读取 API key，也不发起网络请求。

只有用户明确授权生成音频后才能执行：

```bash
novel-tts render run BOOK --env-file .env
novel-tts render run BOOK --chapter 003 --env-file .env
```

重新拼接已有 segment，不调用 API：

```bash
novel-tts render assemble BOOK
novel-tts render assemble BOOK --chapter 003
novel-tts render status BOOK
```

API key 只从 profile 的 `api_key_env` 读取，不进入 YAML、cache、manifest 或输出。Cache hit 不需要对应 profile 的 key。

## `config.yaml`

一个 mixed-profile 配置：

```yaml
target: main-mixed
default_profile: mimo-preset

profiles:
  mimo-preset:
    provider: mimo
    model: mimo-v2.5-tts
    api_key_env: MIMO_API_KEY
    request:
      format: wav
      stream: false
    concurrency: 2
    timeout_seconds: 120
    retries: 2

  mimo-design:
    provider: mimo
    model: mimo-v2.5-tts-voicedesign
    api_key_env: MIMO_API_KEY
    request:
      format: wav
      stream: false
      optimize_text_preview: false
    concurrency: 1
    timeout_seconds: 120
    retries: 2

  mimo-clone:
    provider: mimo
    model: mimo-v2.5-tts-voiceclone
    api_key_env: MIMO_API_KEY
    request:
      format: wav
      stream: false
    concurrency: 1
    timeout_seconds: 120
    retries: 2

output:
  sample_rate: 24000
  channels: 1
  final_format: mp3

assembly:
  chunk_gap_ms: 0
  dialogue_gap_ms: 180
  narration_gap_ms: 260
  scene_gap_ms: 800
  chapter_gap_ms: 1500

execution:
  max_chars_per_request: 200
```

顶层字段：

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `target` | 必填 | 输出和 manifest 名称；只允许 ASCII 字母、数字、`.`、`_`、`-` |
| `default_profile` | 必填 | Voice 未写 `profile` 时使用的 profile |
| `profiles` | 必填 | 一个或多个 provider/model 执行配置 |
| `output.sample_rate` | `24000` | Cache 与拼接 WAV 的采样率 |
| `output.channels` | `1` | Cache 与拼接 WAV 的声道数 |
| `output.final_format` | `mp3` | `wav`、`mp3`、`opus` 或 `m4a` |
| `assembly.chunk_gap_ms` | `0` | 同一 semantic segment 内部 chunk gap |
| `assembly.dialogue_gap_ms` | `180` | Dialogue job 后的 gap |
| `assembly.narration_gap_ms` | `260` | Narration/thought job 后的 gap |
| `assembly.scene_gap_ms` | `800` | Scene 变化时的 gap |
| `assembly.chapter_gap_ms` | `1500` | Chapter 变化时的 gap |
| `execution.max_chars_per_request` | `200` | 单个 request 的文本上限 |

Profile 字段：

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `provider` | 必填 | Adapter ID，目前为 `custom` 或 `mimo` |
| `endpoint` | provider 默认值 | Custom 必填；MiMo 可省略 |
| `model` | 必填 | 该 profile 的具体模型 |
| `api_key_env` | 必填 | API key 环境变量名 |
| `request` | `{}` | Provider-specific 请求参数 |
| `concurrency` | `1` | 该 profile 的最大并发数 |
| `timeout_seconds` | `120` | 单次请求 timeout |
| `retries` | `2` | 可重试错误的额外尝试次数 |

所有 profile 在 planning 阶段验证，即使当前 casting 没有使用它。Provider-specific request 字段见 [providers.md](providers.md)。

## Voice catalog

`voices.yaml` 的每个 voice ID 表示一个**具体可执行音源**：

```yaml
voices:
  narrator-designed:
    profile: mimo-design
    mode: design
    description: 平静、克制的近距离小说旁白声。

  male-old-preset:
    # profile 省略，因此使用 default_profile: mimo-preset
    mode: preset
    voice: 白桦

  protagonist-cloned:
    profile: mimo-clone
    mode: clone
    reference_audio: references/protagonist.wav
```

Loader 会移除通用 `profile` 字段，再将其余字段交给对应 adapter。Voice ID 不表示跨 provider 的抽象音色；如果要保留同一人物的多个方案，应创建多个明确 ID，再在 `voice_used.yaml` 选择一个。

这种结构刻意不支持自动 source 搜索或 fallback。零个或不兼容的 profile/voice 都是 planning error。

## Casting

`voice_used.yaml` 继续保持 speaker 到 voice ID 的简单映射：

```yaml
voices:
  NARRATOR: narrator-designed
  孔乙己: protagonist-cloned
  酒店伙计: male-old-preset
  EXTRA: narrator-designed
```

选择粒度固定为 speaker，不支持按 segment、emotion 或 scene 动态换 profile。多个 speaker 可以共享一个 voice。

正式 render 前要求：

- 每个 effective speaker 都有 selection；
- selection 引用的 voice ID 存在；
- voice 的 profile 存在且 provider-specific 参数有效；
- speaker 是 person 或 system name；
- annotation 和 casting 中都没有 `UNKNOWN`。

## Style compiler

Annotation 使用一个很小的自然语言 style 结构：

```yaml
style:
  direction: 低声、迟疑，后半句逐渐疲惫。
  tags_before: [紧张, 深呼吸]
  tags_after: [苦笑]
```

`direction` 是主要表示，adapter 决定放入 provider 的 instruction、prompt 或其他自然语言入口。标签只保存不带括号的自由文本语义，adapter 决定包装语法。

MiMo 将 direction 放入 `user` message，并把标签编译进 `assistant` 正文，例如 `（紧张｜深呼吸）正文（苦笑）`。Custom 将 style 对象原样发送给私有服务。

长 segment 被 request 长度或 scene 边界切开时，direction 随每个独立请求发送；`tags_before` 只用于整个 semantic segment 的第一块，`tags_after` 只用于最后一块。

Renderer 不提供 emotion/speed/pitch 等结构化 Style IR，也不兼容只接受结构化参数且无法消费自然语言或开放标签的 provider。

## Planner 与执行

Planner 按以下顺序工作：

1. 验证 processed、persons、sparse annotation 和 scenes；
2. 加载并验证所有 profiles；
3. Materialize 默认 narration 并阻止 `UNKNOWN`；
4. 通过 casting 解析 concrete voice 和 profile；
5. 验证实际使用的 provider voice；
6. 根据 scene 边界和 request 长度切分；
7. 使用 job profile 的 provider 编译 style；
8. 计算 cache key 并生成 RenderJob。

每个 RenderJob 明确持有 profile、voice 和 compiled style。执行时：

- 每个使用中的 profile 创建一个共享 HTTP client；
- 每个 profile 使用独立 concurrency semaphore；
- 全局 worker 数为使用中 profile concurrency 之和；
- 不自动 fallback 到其他 profile；
- 所有结果规范化为相同 WAV 后才进入 cache 和 assembly。

## Cache

每个 cache 文件是规范化后的 PCM s16 WAV：

```text
render/cache/<sha256>.wav
```

Cache key 包含：

- cache schema version；
- 实际 provider、endpoint、model 和 request；
- 原始文本和完整 compiled style；
- voice ID 及 provider-specific 参数；
- clone reference 等资源的内容 hash；
- output sample rate、channels 和 final format。

Profile ID 和 target 本身不决定音频，因此不单独进入 cache key；两个执行参数完全相同的 profile 可以复用 cache。Custom provider 会把 voice ID 发给 API，所以 voice ID 本身仍参与 key。API key 永不参与 cache key。

## Audio 与 assembly

Provider 响应先由 ffmpeg 规范化为目标 sample rate、channel count 和 PCM s16 WAV。执行 synthesis 或最终非 WAV 转码前必须安装 ffmpeg。

Gap 优先级：

1. 同一 segment 的内部 chunk gap；
2. chapter gap；
3. scene gap；
4. dialogue 或 narration/thought gap。

只有全部计划 job 成功才会生成最终 chapter/book 音频。失败时保留成功 cache 和 segment，删除可能陈旧的最终拼接文件，并阻止不完整 assembly。

不同 provider/model 即使格式已规范化，也可能存在响度、音色和韵律差异。Mixed target 必须进行人工连续试听。

## Manifest

最近一次 target run 写入：

```text
render/manifests/<target>.json
```

Manifest 顶层记录 target、default profile、实际使用的 profile/provider/model；每个 job 记录 profile、provider、model、voice、semantic style、cache key、cache hit/miss、请求 ID、attempts、elapsed time、duration、输出文件、错误和 assembly 状态。

Manifest 不保存 API key，也不复制正文或 render 配置 snapshot。`novel-tts render status BOOK` 显示当前 config target 的 manifest。

## 明确不支持

为保持 personal-project 架构可理解，renderer 不提供：

- 按 segment/style/scene 自动切换 profile；
- Provider 请求失败后的自动 fallback；
- Capability matrix；
- 自动寻找“兼容”voice；
- 强制 profile 后隐式替换 casting；
- Mixed target selection hash。

需要新版本输出时显式修改 `target`；需要新 casting 时显式修改 `voice_used.yaml`。

## 常见阻塞

### `UNKNOWN speaker cannot be rendered`

回到 annotation workflow 解决 speaker，不要给 `UNKNOWN` 配置 voice。

### `Missing voices`

在 `voice_used.yaml` 中为列出的 effective speaker 选择 voice。

### `profile ... does not reference a profile`

修正 voice 的显式 `profile`，或确认 `default_profile` 存在。

### `mode must be ... for model ...`

MiMo voice mode 与其 profile model 不匹配。修改 profile 或 voice；不要静默转换 mode。

### `environment variable ... is not set`

通过环境或 `--env-file` 提供对应 profile 的 key。不要把 secret 写入 YAML。

### `planned segment(s) are missing`

`render assemble` 只使用当前 target 和当前计划的 segment。先运行 `render run` 补齐。

### ffmpeg error

确认 ffmpeg 已安装，并检查 provider 返回格式与 profile request 一致。
