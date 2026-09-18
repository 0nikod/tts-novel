from pathlib import Path

import pytest

from novel_tts.renderer.capabilities import get_capabilities
from novel_tts.renderer.config import (
    load_render_config,
    load_voice_catalog,
    load_voice_usage,
    render_target,
    resolve_voice_source,
    validate_voice_for_profile,
)
from novel_tts.renderer.models import (
    RenderProfile,
    StreamingMode,
    VoiceMode,
    VoiceSpec,
    VoiceUsage,
)


def test_mimo_models_expose_different_voice_capabilities() -> None:
    preset = get_capabilities("mimo", "mimo-v2.5-tts")
    design = get_capabilities("mimo", "mimo-v2.5-tts-voicedesign")
    clone = get_capabilities("mimo", "mimo-v2.5-tts-voiceclone")

    assert preset.voice_modes == {VoiceMode.PRESET}
    assert design.voice_modes == {VoiceMode.TEXT_DESIGN}
    assert clone.voice_modes == {VoiceMode.INLINE_CLONE}
    assert StreamingMode.REALTIME in preset.streaming_modes
    assert StreamingMode.REALTIME not in design.streaming_modes


def test_catalog_rejects_voice_mode_unsupported_by_model(tmp_path: Path) -> None:
    render = tmp_path / "render"
    render.mkdir()
    (render / "config.yaml").write_text(
        "profiles:\n"
        "  preset:\n"
        "    provider: mimo\n"
        "    model: mimo-v2.5-tts\n"
        "    api_key_env: MIMO_API_KEY\n",
        encoding="utf-8",
    )
    (render / "voices.yaml").write_text(
        "voices:\n"
        "  林冲:\n"
        "    invalid-clone:\n"
        "      profile: preset\n"
        "      kind: inline_clone\n"
        "      reference_audio: voice.wav\n",
        encoding="utf-8",
    )
    config = load_render_config(tmp_path)

    with pytest.raises(ValueError, match="supports: preset"):
        load_voice_catalog(render, config.profiles)


def test_voice_binding_must_match_profile_capabilities(tmp_path: Path) -> None:
    profile = RenderProfile(
        id="mimo-preset",
        provider="mimo",
        model="mimo-v2.5-tts",
        api_key_env="MIMO_API_KEY",
        request={"format": "wav"},
    )
    voice = VoiceSpec(kind=VoiceMode.TEXT_DESIGN, description="沉稳的声音")

    with pytest.raises(ValueError, match="supports: preset"):
        validate_voice_for_profile("林冲", voice, profile)


def test_catalog_and_voice_used_select_per_person_sources(tmp_path: Path) -> None:
    render = tmp_path / "render"
    render.mkdir()
    (render / "config.yaml").write_text(
        "profiles:\n"
        "  fish:\n"
        "    provider: fish_audio\n"
        "    model: s2-pro\n"
        "    api_key_env: FISH_AUDIO_API_KEY\n"
        "  mimo:\n"
        "    provider: mimo\n"
        "    model: mimo-v2.5-tts\n"
        "    api_key_env: MIMO_API_KEY\n",
        encoding="utf-8",
    )
    (render / "voices.yaml").write_text(
        "voices:\n"
        "  林冲:\n"
        "    fish-main:\n"
        "      profile: fish\n"
        "      kind: saved_reference\n"
        "      reference_id: lin-chong\n"
        "    mimo-preset:\n"
        "      profile: mimo\n"
        "      kind: preset\n"
        "      voice: 白桦\n"
        "    mimo-alternate:\n"
        "      profile: mimo\n"
        "      kind: preset\n"
        "      voice: 苏打\n",
        encoding="utf-8",
    )
    (render / "voice_used.yaml").write_text("default_profile: fish\nvoices: {}\n", encoding="utf-8")
    config = load_render_config(tmp_path)
    catalog = load_voice_catalog(config.root, config.profiles)
    usage = load_voice_usage(config.root, catalog, config.profiles)

    fish = resolve_voice_source("林冲", catalog, usage)
    overridden_usage = VoiceUsage(default_profile="fish", overrides={"林冲": "mimo-preset"})
    mimo = resolve_voice_source("林冲", catalog, overridden_usage)

    assert fish.id == "fish-main"
    assert fish.voice.kind == VoiceMode.SAVED_REFERENCE
    assert mimo.voice.voice == "白桦"
    assert mimo.profile_id == "mimo"
    with pytest.raises(ValueError, match="multiple sources"):
        resolve_voice_source("林冲", catalog, usage, forced_profile="mimo")

    target = render_target(None, overridden_usage)
    alternate_target = render_target(
        None,
        VoiceUsage(default_profile="fish", overrides={"林冲": "mimo-alternate"}),
    )
    assert target.startswith("mixed-")
    assert target != alternate_target


def test_unknown_model_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported renderer model"):
        get_capabilities("mimo", "future-model")
