import wave
from pathlib import Path

from novel_tts.renderer.audio import concatenate_wav, duration_ms
from novel_tts.renderer.models import OutputConfig


def write_silence(path: Path, duration: int, sample_rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * round(sample_rate * duration / 1000))


def test_concatenate_wav_adds_configured_gap(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "output.wav"
    write_silence(first, 100)
    write_silence(second, 200)

    concatenate_wav(
        [(first, 50), (second, 0)],
        output,
        OutputConfig(sample_rate=24000, channels=1),
    )

    assert duration_ms(output) == 350
