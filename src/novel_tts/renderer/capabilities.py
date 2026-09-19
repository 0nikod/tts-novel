from __future__ import annotations

from .models import ModelCapabilities, StreamingMode, VoiceMode

_MODELS: dict[tuple[str, str], ModelCapabilities] = {}


def _register(capability: ModelCapabilities) -> None:
    _MODELS[(capability.provider, capability.model)] = capability


for fish_model in ("s2-pro", "s2.1-pro", "s2.1-pro-free"):
    _register(
        ModelCapabilities(
            provider="fish_audio",
            model=fish_model,
            voice_modes=frozenset({VoiceMode.SAVED_REFERENCE, VoiceMode.INLINE_CLONE}),
            streaming_modes=frozenset({StreamingMode.NONE}),
            output_formats=frozenset({"wav", "pcm", "mp3", "opus"}),
            style_controls=frozenset({"bracket_tags", "prosody"}),
            supports_multi_speaker=True,
            supports_timestamps=True,
            reference_audio_formats=frozenset({"wav", "mp3", "flac", "m4a", "ogg"}),
        )
    )

_register(
    ModelCapabilities(
        provider="mimo",
        model="mimo-v2.5-tts",
        voice_modes=frozenset({VoiceMode.PRESET}),
        streaming_modes=frozenset({StreamingMode.NONE, StreamingMode.REALTIME}),
        output_formats=frozenset({"wav", "mp3", "pcm", "pcm16"}),
        style_controls=frozenset({"natural_language", "inline_audio_tags"}),
    )
)
_register(
    ModelCapabilities(
        provider="mimo",
        model="mimo-v2.5-tts-voicedesign",
        voice_modes=frozenset({VoiceMode.TEXT_DESIGN}),
        streaming_modes=frozenset({StreamingMode.NONE, StreamingMode.BUFFERED}),
        output_formats=frozenset({"wav", "mp3", "pcm", "pcm16"}),
        style_controls=frozenset({"natural_language", "inline_audio_tags"}),
    )
)
_register(
    ModelCapabilities(
        provider="mimo",
        model="mimo-v2.5-tts-voiceclone",
        voice_modes=frozenset({VoiceMode.INLINE_CLONE}),
        streaming_modes=frozenset({StreamingMode.NONE, StreamingMode.BUFFERED}),
        output_formats=frozenset({"wav", "mp3", "pcm", "pcm16"}),
        style_controls=frozenset({"natural_language", "inline_audio_tags"}),
        reference_audio_formats=frozenset({"wav", "mp3"}),
        max_reference_audio_bytes=10 * 1024 * 1024,
    )
)


def get_capabilities(provider: str, model: str) -> ModelCapabilities:
    try:
        return _MODELS[(provider, model)]
    except KeyError as error:
        raise ValueError(
            f"unsupported renderer model {provider}/{model}; update the model registry"
        ) from error


def all_capabilities() -> list[ModelCapabilities]:
    return sorted(_MODELS.values(), key=lambda item: (item.provider, item.model))
