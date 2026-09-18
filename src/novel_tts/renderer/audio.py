from __future__ import annotations

import shutil
import subprocess
import wave
from collections.abc import Iterable
from pathlib import Path

from .models import OutputConfig


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise ValueError("ffmpeg is required for rendering but was not found in PATH")


def normalize_audio(
    source: Path,
    destination: Path,
    *,
    input_format: str,
    output: OutputConfig,
    input_sample_rate: int | None = None,
) -> None:
    require_ffmpeg()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part.wav")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if input_format in {"pcm", "pcm16"}:
        command.extend(
            [
                "-f",
                "s16le",
                "-ar",
                str(input_sample_rate or 24000),
                "-ac",
                "1",
            ]
        )
    command.extend(
        [
            "-i",
            str(source),
            "-ar",
            str(output.sample_rate),
            "-ac",
            str(output.channels),
            "-c:a",
            "pcm_s16le",
            str(temporary),
        ]
    )
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"ffmpeg failed to normalize audio: {result.stderr.strip()[:500]}")
    validate_canonical_wave(temporary, output)
    temporary.replace(destination)


def duration_ms(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as audio:
            return round(audio.getnframes() * 1000 / audio.getframerate())
    except (EOFError, wave.Error) as error:
        raise ValueError(f"invalid WAV audio: {path}") from error


def concatenate_wav(
    inputs: Iterable[tuple[Path, int]], destination: Path, output: OutputConfig
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part.wav")
    silence_frame = b"\x00\x00" * output.channels
    with wave.open(str(temporary), "wb") as target:
        target.setnchannels(output.channels)
        target.setsampwidth(2)
        target.setframerate(output.sample_rate)
        for path, gap_ms in inputs:
            validate_canonical_wave(path, output)
            with wave.open(str(path), "rb") as source:
                target.writeframes(source.readframes(source.getnframes()))
            silence_frames = round(output.sample_rate * gap_ms / 1000)
            target.writeframes(silence_frame * silence_frames)
    temporary.replace(destination)


def transcode_final(source: Path, destination: Path) -> None:
    require_ffmpeg()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.stem}.part{destination.suffix}")
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            str(temporary),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"ffmpeg failed to transcode final audio: {result.stderr.strip()[:500]}")
    temporary.replace(destination)


def validate_canonical_wave(path: Path, output: OutputConfig) -> None:
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getframerate() != output.sample_rate:
                raise ValueError(f"unexpected sample rate in {path}")
            if audio.getnchannels() != output.channels:
                raise ValueError(f"unexpected channel count in {path}")
            if audio.getsampwidth() != 2:
                raise ValueError(f"unexpected sample width in {path}")
            if audio.getnframes() <= 0:
                raise ValueError(f"audio file is empty: {path}")
    except (EOFError, wave.Error) as error:
        raise ValueError(f"invalid WAV audio: {path}") from error
