# TTS providers

Renderer 通过小型 adapter registry 支持多个 TTS provider。Annotation、persons 和 scenes 永远不包含 provider、profile、model、voice ID 或请求参数。

当前内置：

```text
custom   通用私有 JSON TTS 接口
mimo     Xiaomi MiMo V2.5 TTS
```

使用 `novel-tts render providers` 查看 adapter 和已知模型。

## Profile 与 voice 的边界

Profile 是一组具体执行设置：

```yaml
profiles:
  mimo-preset:
    provider: mimo
    model: mimo-v2.5-tts
    api_key_env: MIMO_API_KEY
    request:
      format: wav
      stream: false
```

Voice 是一个绑定 profile 的具体音源：

```yaml
voices:
  supporting-preset:
    # 省略 profile 时使用 config.default_profile
    mode: preset
    voice: 白桦

  narrator-designed:
    profile: mimo-design
    mode: design
    description: 平静、克制的近距离小说旁白声。
```

Adapter 只接收 voice 中除 `profile` 外的字段。一个计划可以包含多个 profile，但每个 speaker 只选择一个 voice；不会自动 fallback 或搜索其他 source。

## Custom provider

Profile 示例：

```yaml
profiles:
  custom-main:
    provider: custom
    endpoint: http://127.0.0.1:8000/v1/tts
    model: custom-model
    api_key_env: TTS_API_KEY
    request:
      audio_format: wav
      response_kind: auto   # auto | audio | json
      parameters: {}        # 可选，原样放入请求 parameters
```

Voice 参数由私有 API 定义：

```yaml
voices:
  narrator-private:
    profile: custom-main
    reference_id: <real-private-reference-id>
```

请求使用 Bearer authentication：

```json
{
  "model": "custom-model",
  "text": "朗读文本",
  "voice": {
    "reference_id": "<real-private-reference-id>",
    "id": "narrator-private"
  },
  "style": {
    "direction": "平静、克制地朗读。",
    "tags_before": ["深呼吸"]
  }
}
```

成功响应可以是直接音频 body，也可以是 JSON：

```json
{
  "audio_base64": "...",
  "format": "wav"
}
```

JSON 也接受 `audio` 作为 Base64 字段名。`response_kind: auto` 根据 Content-Type 区分音频与 JSON。

## Xiaomi MiMo V2.5 TTS

官方文档：

- [MiMo V2.5 TTS 使用指南](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis-v2.5)
- [MiMo TTS API](https://mimo.mi.com/docs/zh-CN/api/speech/tts)
- [速率限制](https://mimo.mi.com/docs/zh-CN/api/guidance/rate-limit)
- [错误码](https://mimo.mi.com/docs/zh-CN/api/guidance/error-codes)

MiMo profile 的 `endpoint` 可省略，默认：

```text
https://api.xiaomimimo.com/v1/chat/completions
```

Adapter 使用 `api-key` 请求头。目标正文放在 `assistant` message；语气、风格、音色设计描述放在 `user` message。非流式响应从 `choices[0].message.audio.data` 读取 Base64 音频。

MiMo voice 使用必填 `mode`，并且必须与 profile model 匹配：

| `mode` | Profile `model` | 必填 voice 字段 |
|---|---|---|
| `preset` | `mimo-v2.5-tts` | `voice` |
| `design` | `mimo-v2.5-tts-voicedesign` | `description` |
| `clone` | `mimo-v2.5-tts-voiceclone` | `reference_audio` |

不同 mode 可以存在于同一计划，只要分别绑定兼容 profile。

### Preset

```yaml
profiles:
  mimo-preset:
    provider: mimo
    model: mimo-v2.5-tts
    api_key_env: MIMO_API_KEY
    request:
      format: wav
      stream: false

voices:
  narrator-preset:
    profile: mimo-preset
    mode: preset
    voice: 冰糖
    instruction: 平静、自然，像近距离讲故事。   # 可选
```

支持的 Voice ID：

```text
mimo_default  冰糖  茉莉  苏打  白桦  Mia  Chloe  Milo  Dean
```

中国集群的 `mimo_default` 当前对应冰糖。显式写音色名可以避免集群默认值变化。

### Voice design

```yaml
profiles:
  mimo-design:
    provider: mimo
    model: mimo-v2.5-tts-voicedesign
    api_key_env: MIMO_API_KEY
    request:
      format: wav
      optimize_text_preview: true

voices:
  heroine-designed:
    profile: mimo-design
    mode: design
    description: 高中女生，声音柔和清晰，略带紧张感。
    instruction: 不要夸张，不要使用卡通声线。   # 可选
```

`description` 必填，并成为 `user` message 的一部分。`optimize_text_preview` 只允许用于 voice-design profile。Renderer 始终提供明确 assistant 目标文本，不依赖 MiMo 自动生成正文。

### Voice clone

```yaml
profiles:
  mimo-clone:
    provider: mimo
    model: mimo-v2.5-tts-voiceclone
    api_key_env: MIMO_API_KEY
    request:
      format: wav

voices:
  cloned-voice:
    profile: mimo-clone
    mode: clone
    reference_audio: references/voice.wav
    instruction: 自然、克制地朗读。   # 可选
```

相对路径以 `render/` 为基准。只接受 MP3/WAV。Adapter 生成官方要求的 `data:<MIME>;base64,...`，并验证完整 data URL 不超过 10 MB。Cache key 使用参考音频内容 SHA-256。

### Streaming

Profile request：

```yaml
request:
  format: pcm16
  stream: true
```

MiMo 官方要求流式音频使用 PCM16。Adapter 从 SSE 的 `choices[0].delta.audio.data` 解码 chunk，按顺序拼接，并按 24 kHz、mono、signed PCM16 交给规范化层。

`mimo-v2.5-tts` 支持低延迟增量输出；design 和 clone 流式接口目前属于兼容模式，可能在推理结束后才返回一个 chunk。Renderer 会缓冲完整响应，因此 streaming 用于协议兼容而非边生成边播放。

### Style compilation

Annotation 中的 style 只包含自然语言和 segment 边界标签：

```yaml
style:
  direction: 声音压低，略显迟疑，后半句逐渐疲惫。
  tags_before: [紧张, 深呼吸]
  tags_after: [苦笑]
```

MiMo adapter 将 `direction` 原样加入 `user` message。标签由 adapter 包装后加入 `assistant` 正文：

```text
（紧张｜深呼吸）正文（苦笑）
```

Annotation 不保存括号或 MiMo 专用语法。Style 没有明确文本或可靠上下文证据时应完全省略。

## Retry policy

每个 profile 使用自己的 timeout、retries 和 concurrency。共享 HTTP runner 对以下情况执行有限指数退避并加入 jitter：

- transport error 和 timeout；
- HTTP 408、409、429；
- 任意 HTTP 5xx。

普通 HTTP 4xx、成功响应中的协议错误和无效 Base64 不重试。失败 manifest 保留尝试次数和耗时。MiMo 限流按账户和模型聚合，不应通过更换 API key 绕过。
