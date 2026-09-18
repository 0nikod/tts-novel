import base64
import json
from pathlib import Path

from novel_tts.renderer.models import (
    CompiledStyle,
    PreparedRequest,
    RenderJob,
    RenderProfile,
    VoiceMode,
    VoiceSpec,
)
from novel_tts.renderer.providers.fish import FishAudioDriver
from novel_tts.renderer.providers.mimo import MimoDriver
from novel_tts.renderer.style import compile_style


def make_job(profile: RenderProfile, voice: VoiceSpec, compiled: CompiledStyle) -> RenderJob:
    return RenderJob(
        id="01-000001-000001",
        chapter="01",
        line_start=1,
        line_end=1,
        scene_id="S0001",
        name="林冲",
        text_type="dialogue",
        source_text="住手！",
        style={"delivery": "shout", "volume": "high"},
        review=False,
        review_reason=None,
        profile=profile,
        voice=voice,
        voice_source="test-source",
        chunk_index=1,
        chunk_count=1,
        compiled=compiled,
        cache_key="hash",
    )


def test_fish_request_uses_reference_id_and_bracket_style(tmp_path: Path) -> None:
    profile = RenderProfile(
        id="fish",
        provider="fish_audio",
        model="s2-pro",
        api_key_env="FISH_AUDIO_API_KEY",
        request={"format": "wav", "chunk_length": 300},
    )
    compiled = compile_style(profile, "住手！", {"delivery": "shout", "volume": "high"})
    job = make_job(
        profile,
        VoiceSpec(kind=VoiceMode.SAVED_REFERENCE, reference_id="voice-id"),
        compiled,
    )

    request = FishAudioDriver().prepare(job, "secret")

    assert request.headers["model"] == "s2-pro"
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.json_body is not None
    assert request.json_body["reference_id"] == "voice-id"
    assert request.json_body["text"] == "[shouting][loud]住手！"
    assert request.json_body["prosody"]["volume"] == 3


def test_mimo_preset_request_separates_instruction_and_spoken_text(tmp_path: Path) -> None:
    profile = RenderProfile(
        id="mimo",
        provider="mimo",
        model="mimo-v2.5-tts",
        api_key_env="MIMO_API_KEY",
        request={"format": "wav", "stream": False},
    )
    compiled = compile_style(profile, "住手！", {"delivery": "shout", "volume": "high"})
    job = make_job(profile, VoiceSpec(kind=VoiceMode.PRESET, voice="白桦"), compiled)

    request = MimoDriver().prepare(job, "secret")

    assert request.headers["api-key"] == "secret"
    assert request.json_body is not None
    assert request.json_body["audio"] == {"format": "wav", "voice": "白桦"}
    assert request.json_body["messages"][0]["role"] == "user"
    assert "提高音量" in request.json_body["messages"][0]["content"]
    assert request.json_body["messages"][-1] == {
        "role": "assistant",
        "content": "住手！",
    }


def test_mimo_voice_design_uses_description_instead_of_preset_voice(tmp_path: Path) -> None:
    profile = RenderProfile(
        id="mimo-design",
        provider="mimo",
        model="mimo-v2.5-tts-voicedesign",
        api_key_env="MIMO_API_KEY",
        request={"format": "wav", "stream": False},
    )
    job = make_job(
        profile,
        VoiceSpec(kind=VoiceMode.TEXT_DESIGN, description="低沉清晰的男性声音"),
        CompiledStyle(text="住手！"),
    )

    request = MimoDriver().prepare(job, "secret")

    assert request.json_body is not None
    assert request.json_body["audio"] == {"format": "wav"}
    assert request.json_body["messages"][0] == {
        "role": "user",
        "content": "低沉清晰的男性声音",
    }


def test_mimo_clone_encodes_reference_as_data_uri(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"reference")
    profile = RenderProfile(
        id="mimo-clone",
        provider="mimo",
        model="mimo-v2.5-tts-voiceclone",
        api_key_env="MIMO_API_KEY",
        request={"format": "wav", "stream": False},
    )
    job = make_job(
        profile,
        VoiceSpec(kind=VoiceMode.INLINE_CLONE, reference_audio=reference),
        CompiledStyle(text="住手！"),
    )

    request = MimoDriver().prepare(job, "secret")

    assert request.json_body is not None
    assert request.json_body["audio"]["voice"].startswith("data:audio/wav;base64,")


def test_mimo_non_streaming_response_decodes_base64() -> None:
    encoded = base64.b64encode(b"wave-data").decode()
    body = json.dumps({"choices": [{"message": {"audio": {"data": encoded}}}]}).encode()
    request = PreparedRequest(url="test", headers={}, response_kind="base64_json")

    result = MimoDriver().decode(request, body)

    assert result.audio == b"wave-data"
