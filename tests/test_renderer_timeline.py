import json
import wave
from pathlib import Path

from novel_tts.renderer.audio import concatenate_wav
from novel_tts.renderer.models import (
    CompiledStyle,
    OutputConfig,
    RenderConfig,
    RenderJob,
    RenderProfile,
    VoiceMode,
    VoiceSpec,
)
from novel_tts.renderer.timeline import write_timeline


def write_silence(path: Path, duration: int, sample_rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * round(sample_rate * duration / 1000))


def make_job(identifier: str, line: int, text: str, profile: RenderProfile) -> RenderJob:
    return RenderJob(
        id=identifier,
        chapter="01",
        line_start=line,
        line_end=line,
        scene_id="S0001",
        name="林冲",
        text_type="dialogue",
        source_text=text,
        style=None,
        review=False,
        review_reason=None,
        profile=profile,
        voice=VoiceSpec(kind=VoiceMode.PRESET, voice="白桦"),
        voice_source="mimo-test",
        chunk_index=1,
        chunk_count=1,
        compiled=CompiledStyle(text=text),
        cache_key=identifier,
    )


def test_timeline_uses_pcm_frames_and_includes_assembly_gap(tmp_path: Path) -> None:
    profile = RenderProfile(
        id="mimo",
        provider="mimo",
        model="mimo-v2.5-tts",
        api_key_env="MIMO_API_KEY",
        request={"format": "wav"},
    )
    first = tmp_path / "segments" / "first.wav"
    second = tmp_path / "segments" / "second.wav"
    first.parent.mkdir()
    write_silence(first, 100)
    write_silence(second, 200)
    assembled = tmp_path / "book.wav"
    concatenate_wav([(first, 50), (second, 0)], assembled, OutputConfig())
    jobs = [
        (make_job("01-1", 1, "第一句。", profile), first, 50),
        (make_job("01-2", 2, "第二句。", profile), second, 0),
    ]
    config = RenderConfig(root=tmp_path, profiles={"mimo": profile})

    positions = write_timeline(
        jobs,
        audio_path=assembled,
        destination=tmp_path / "timeline.json",
        output_root=tmp_path,
        config=config,
        scope="book",
    )

    data = json.loads((tmp_path / "timeline.json").read_text(encoding="utf-8"))
    assert positions["01-1"] == (0, 2400)
    assert positions["01-2"] == (3600, 8400)
    assert data["duration_frames"] == 8400
    assert data["segments"][0]["gap_after_ms"] == 50
    assert data["segments"][1]["start_ms"] == 150
    assert data["events"][1]["kind"] == "silence"
    assert (
        (tmp_path / "subtitles.srt")
        .read_text(encoding="utf-8")
        .startswith("1\n00:00:00,000 --> 00:00:00,100")
    )
    assert (tmp_path / "subtitles.vtt").exists()
