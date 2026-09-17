from pathlib import Path

import pytest

from novel_tts.renderer.capabilities import get_capabilities
from novel_tts.renderer.config import load_render_config, validate_voice_for_profile
from novel_tts.renderer.models import RenderProfile, StreamingMode, VoiceMode, VoiceSpec


def test_mimo_models_expose_different_voice_capabilities() -> None:
    preset = get_capabilities("mimo", "mimo-v2.5-tts")
    design = get_capabilities("mimo", "mimo-v2.5-tts-voicedesign")
    clone = get_capabilities("mimo", "mimo-v2.5-tts-voiceclone")

    assert preset.voice_modes == {VoiceMode.PRESET}
    assert design.voice_modes == {VoiceMode.TEXT_DESIGN}
    assert clone.voice_modes == {VoiceMode.INLINE_CLONE}
    assert StreamingMode.REALTIME in preset.streaming_modes
    assert StreamingMode.REALTIME not in design.streaming_modes


def test_config_rejects_voice_mode_unsupported_by_model(tmp_path: Path) -> None:
    render = tmp_path / "render"
    render.mkdir()
    (render / "config.yaml").write_text(
        "default_profile: invalid\n"
        "profiles:\n"
        "  invalid:\n"
        "    provider: mimo\n"
        "    model: mimo-v2.5-tts\n"
        "    voice_mode: inline_clone\n"
        "    voice_file: voices.yaml\n"
        "    api_key_env: MIMO_API_KEY\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not support inline_clone"):
        load_render_config(tmp_path)


def test_voice_binding_must_match_profile_mode(tmp_path: Path) -> None:
    profile = RenderProfile(
        id="mimo-preset",
        provider="mimo",
        model="mimo-v2.5-tts",
        voice_mode=VoiceMode.PRESET,
        voice_file=tmp_path / "voices.yaml",
        api_key_env="MIMO_API_KEY",
        request={"format": "wav"},
    )
    voice = VoiceSpec(kind=VoiceMode.TEXT_DESIGN, description="沉稳的声音")

    with pytest.raises(ValueError, match="supports: preset"):
        validate_voice_for_profile("林冲", voice, profile)


def test_unknown_model_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported renderer model"):
        get_capabilities("mimo", "future-model")
