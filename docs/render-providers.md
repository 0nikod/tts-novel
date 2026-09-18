# Renderer providers and models

This document lists the provider/model contract implemented by the current code. Provider APIs may evolve; update the capability registry, driver, tests, and this document together.

For the common YAML schema and workflow, see [render-configuration.md](render-configuration.md).

## Capability matrix

| Provider | Model | Voice kinds | Request formats | Streaming mode |
|---|---|---|---|---|
| `fish_audio` | `s2-pro` | `saved_reference`, `inline_clone` | `wav`, `pcm`, `mp3`, `opus` | capability known, but current Fish driver sends complete-response jobs |
| `fish_audio` | `s2.1-pro` | `saved_reference`, `inline_clone` | `wav`, `pcm`, `mp3`, `opus` | same |
| `fish_audio` | `s2.1-pro-free` | `saved_reference`, `inline_clone` | `wav`, `pcm`, `mp3`, `opus` | same |
| `mimo` | `mimo-v2.5-tts` | `preset` | `wav`, `mp3`, `pcm`, `pcm16` | non-streaming or realtime SSE |
| `mimo` | `mimo-v2.5-tts-voicedesign` | `text_design` | `wav`, `mp3`, `pcm`, `pcm16` | non-streaming or buffered SSE |
| `mimo` | `mimo-v2.5-tts-voiceclone` | `inline_clone` | `wav`, `mp3`, `pcm`, `pcm16` | non-streaming or buffered SSE |

The renderer buffers each provider result before normalization and file assembly. `stream: true` does not make the command an interactive playback client.

## MiMo

### Authentication

```yaml
api_key_env: MIMO_API_KEY
```

The driver sends the value in the `api-key` header. Never place the key itself in YAML.

### Preset profile

```yaml
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
    retries: 4
    style_policy:
      unsupported: error
```

Voice source:

```yaml
voices:
  小明:
    mimo-preset:
      profile: mimo-preset
      kind: preset
      voice: provider-preset-name
```

Preset names are provider data and are not enumerated by the local capability registry. Use a name confirmed by the provider or the user; a non-empty but invalid name may only be rejected by the API.

### Voice-design profile

```yaml
profiles:
  mimo-design:
    provider: mimo
    model: mimo-v2.5-tts-voicedesign
    api_key_env: MIMO_API_KEY
    request:
      format: wav
      stream: false
      optimize_text_preview: true
    concurrency: 1
    timeout_seconds: 180
    retries: 3
    style_policy:
      unsupported: error
```

Voice source:

```yaml
voices:
  小明:
    mimo-design:
      profile: mimo-design
      kind: text_design
      description: 清晰自然的青年男性声音，音色温暖。
```

`optimize_text_preview` is accepted only for `text_design` jobs.

### Voice-clone profile

```yaml
profiles:
  mimo-clone:
    provider: mimo
    model: mimo-v2.5-tts-voiceclone
    api_key_env: MIMO_API_KEY
    request:
      format: wav
      stream: false
    concurrency: 1
    timeout_seconds: 180
    retries: 3
    style_policy:
      unsupported: error
```

Voice source:

```yaml
voices:
  小明:
    mimo-clone:
      profile: mimo-clone
      kind: inline_clone
      reference_audio: references/xiaoming.wav
```

Current accepted reference extensions are WAV and MP3. The encoded data URI must not exceed 10 MiB, so the raw file limit is approximately 7.5 MiB. Validation happens before the paid request.

### MiMo request fields

Only these keys are accepted under `profile.request`:

| Field | Default | Notes |
|---|---:|---|
| `format` | `wav` | `wav`, `mp3`, `pcm`, or `pcm16` |
| `stream` | `false` | `true` requires `format: pcm16` |
| `optimize_text_preview` | `false` | Only valid for the voice-design model |

Any extra field is rejected while building the render plan.

### MiMo style conversion

Common styles become a natural-language `user` instruction, while spoken text is sent as an `assistant` message. For example:

```yaml
emotion: happy
volume: high
```

becomes approximately:

```text
请使用高兴、提高音量的方式朗读。
```

Vocal actions are inserted into spoken text as parenthesized markers such as `（笑）`. Custom terms come from the `mimo` section of `styles.yaml`.

## Fish Audio

### Authentication

```yaml
api_key_env: FISH_AUDIO_API_KEY
```

The driver sends `Authorization: Bearer ...` and the exact model in the `model` header.

### Profile

```yaml
profiles:
  fish-s2-pro:
    provider: fish_audio
    model: s2-pro
    api_key_env: FISH_AUDIO_API_KEY
    request:
      format: wav
      sample_rate: 24000
      latency: normal
      chunk_length: 300
      normalize: true
      temperature: 0.7
      top_p: 0.7
      prosody:
        speed: 1.0
        volume: 0
        normalize_loudness: true
    concurrency: 2
    timeout_seconds: 120
    retries: 4
    style_policy:
      unsupported: error
```

The current Fish driver sends complete-response requests. Omit `stream` or keep it false when writing renderer configuration; realtime playback is not exposed by this CLI.

### Saved reference

```yaml
voices:
  小明:
    fish-saved:
      profile: fish-s2-pro
      kind: saved_reference
      reference_id: provider-owned-reference-id
```

Do not invent a reference ID. It must already exist in the user's provider account.

### Inline clone

```yaml
voices:
  小明:
    fish-inline:
      profile: fish-s2-pro
      kind: inline_clone
      reference_audio: references/xiaoming.wav
      reference_text: 与参考录音逐字对应的文本
```

Current accepted reference extensions are WAV, MP3, FLAC, M4A, and OGG. `reference_text` is mandatory for Fish inline cloning. The request is encoded as MessagePack rather than JSON.

### Fish request fields

The driver accepts these keys under `profile.request`:

```text
format
sample_rate
latency
chunk_length
normalize
temperature
top_p
prosody
mp3_bitrate
opus_bitrate
max_new_tokens
repetition_penalty
min_chunk_length
condition_on_previous_chunks
early_stop_threshold
stream
```

Additional local checks include:

- `chunk_length` must be an integer from 100 through 300;
- `latency` must be `normal`, `balanced`, or `low`;
- when `format: mp3`, `mp3_bitrate` must be 64, 128, or 192.

Other accepted fields are passed through to the provider. Use values supported by the current provider API rather than guessing.

### Fish style conversion

Common styles become bracket tags around the text. Pace and volume can also override `prosody` values. For example:

```yaml
emotion: happy
volume: high
```

can produce:

```text
[happy][loud]正文
```

and a `prosody.volume` override. Custom Fish mappings come from the `fish_audio` section of `styles.yaml`.

## Adding or changing provider support

Provider behavior is defined in four places:

```text
src/novel_tts/renderer/capabilities.py
src/novel_tts/renderer/style.py
src/novel_tts/renderer/providers/<provider>.py
tests/test_renderer_*.py
```

The provider's official protocol is the source of truth for HTTP fields. This project owns the provider-neutral voice/style representation and the deterministic adapter mapping. Do not add undocumented fallback behavior.

When changing a model contract:

1. update the capability registry;
2. update request validation and preparation;
3. update response decoding if necessary;
4. add prohibited-combination and golden-payload tests;
5. update this document;
6. run Ruff, pytest, `render validate-config`, and a dry-run plan before any paid smoke test.
