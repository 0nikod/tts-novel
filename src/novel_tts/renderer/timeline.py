from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path
from typing import Any

from .models import RenderConfig, RenderJob

TimelineItem = tuple[RenderJob, Path, int]


def write_timeline(
    items: list[TimelineItem],
    *,
    audio_path: Path,
    destination: Path,
    output_root: Path,
    config: RenderConfig,
    scope: str,
    global_positions: dict[str, tuple[int, int]] | None = None,
) -> dict[str, tuple[int, int]]:
    sample_rate = config.output.sample_rate
    cursor = 0
    segments: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    positions: dict[str, tuple[int, int]] = {}

    for index, (job, path, gap_ms) in enumerate(items, 1):
        frames = _frame_count(path)
        start_frame = cursor
        end_frame = start_frame + frames
        gap_frames = round(sample_rate * gap_ms / 1000)
        positions[job.id] = (start_frame, end_frame)
        segment: dict[str, Any] = {
            "index": index,
            "job_id": job.id,
            "chapter": job.chapter,
            "line": (
                job.line_start
                if job.line_start == job.line_end
                else f"{job.line_start}-{job.line_end}"
            ),
            "scene_id": job.scene_id,
            "name": job.name,
            "type": job.text_type,
            "text": job.source_text,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "start_ms": _frames_to_ms(start_frame, sample_rate),
            "end_ms": _frames_to_ms(end_frame, sample_rate),
            "duration_ms": _frames_to_ms(frames, sample_rate),
            "gap_after_ms": _frames_to_ms(gap_frames, sample_rate),
            "audio_file": str(path.relative_to(output_root)),
        }
        if global_positions is not None and job.id in global_positions:
            book_start, book_end = global_positions[job.id]
            segment.update(
                {
                    "book_start_frame": book_start,
                    "book_end_frame": book_end,
                    "book_start_ms": _frames_to_ms(book_start, sample_rate),
                    "book_end_ms": _frames_to_ms(book_end, sample_rate),
                }
            )
        segments.append(segment)
        events.append(
            {
                "kind": "segment",
                "job_id": job.id,
                "start_frame": start_frame,
                "end_frame": end_frame,
            }
        )
        cursor = end_frame
        if gap_frames:
            if config.timeline.include_silence_events:
                events.append(
                    {
                        "kind": "silence",
                        "reason": _gap_reason(job, items[index][0]),
                        "start_frame": cursor,
                        "end_frame": cursor + gap_frames,
                        "start_ms": _frames_to_ms(cursor, sample_rate),
                        "end_ms": _frames_to_ms(cursor + gap_frames, sample_rate),
                    }
                )
            cursor += gap_frames

    actual_frames = _frame_count(audio_path)
    if actual_frames != cursor:
        raise ValueError(
            f"timeline frame count {cursor} does not match assembled audio {actual_frames}"
        )
    data: dict[str, Any] = {
        "schema_version": 1,
        "scope": scope,
        "audio_file": str(audio_path.relative_to(output_root)),
        "audio_sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest(),
        "timebase": {"unit": "pcm_frame", "sample_rate": sample_rate},
        "channels": config.output.channels,
        "duration_frames": actual_frames,
        "duration_ms": _frames_to_ms(actual_frames, sample_rate),
        "segments": segments,
        "scenes": _aggregate_ranges(segments, "scene_id", sample_rate),
        "chapters": _aggregate_ranges(segments, "chapter", sample_rate),
    }
    if config.timeline.include_silence_events:
        data["events"] = events
    _write_json_atomic(destination, data)
    _write_subtitles(destination, segments, config)
    return positions


def _aggregate_ranges(
    segments: list[dict[str, Any]], key: str, sample_rate: int
) -> list[dict[str, Any]]:
    ranges: dict[str, dict[str, int | str]] = {}
    for segment in segments:
        value = str(segment[key])
        if value not in ranges:
            ranges[value] = {
                key: value,
                "start_frame": int(segment["start_frame"]),
                "end_frame": int(segment["end_frame"]),
            }
        else:
            ranges[value]["end_frame"] = int(segment["end_frame"])
    output: list[dict[str, Any]] = []
    for item in ranges.values():
        start = int(item["start_frame"])
        end = int(item["end_frame"])
        output.append(
            {
                **item,
                "start_ms": _frames_to_ms(start, sample_rate),
                "end_ms": _frames_to_ms(end, sample_rate),
                "duration_ms": _frames_to_ms(end - start, sample_rate),
            }
        )
    return output


def _write_subtitles(
    timeline_path: Path, segments: list[dict[str, Any]], config: RenderConfig
) -> None:
    subtitle_segments = [
        segment
        for segment in segments
        if config.timeline.include_narration or segment["type"] != "narration"
    ]
    for subtitle_format in config.timeline.subtitle_formats:
        if timeline_path.name == "timeline.json":
            destination = timeline_path.with_name(f"subtitles.{subtitle_format}")
        else:
            destination = timeline_path.with_suffix(f".{subtitle_format}")
        if subtitle_format == "srt":
            content = _format_srt(subtitle_segments, config.timeline.show_speaker)
        else:
            content = _format_vtt(subtitle_segments, config.timeline.show_speaker)
        destination.write_text(content, encoding="utf-8")


def _format_srt(segments: list[dict[str, Any]], show_speaker: bool) -> str:
    blocks = []
    for index, segment in enumerate(segments, 1):
        text = _subtitle_text(segment, show_speaker)
        blocks.append(
            f"{index}\n{_timestamp(int(segment['start_ms']), ',')} --> "
            f"{_timestamp(int(segment['end_ms']), ',')}\n{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _format_vtt(segments: list[dict[str, Any]], show_speaker: bool) -> str:
    blocks = ["WEBVTT"]
    for segment in segments:
        text = _subtitle_text(segment, show_speaker)
        blocks.append(
            f"{_timestamp(int(segment['start_ms']), '.')} --> "
            f"{_timestamp(int(segment['end_ms']), '.')}\n{text}"
        )
    return "\n\n".join(blocks) + "\n"


def _subtitle_text(segment: dict[str, Any], show_speaker: bool) -> str:
    text = str(segment["text"])
    return f"[{segment['name']}] {text}" if show_speaker else text


def _timestamp(milliseconds: int, separator: str) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _gap_reason(current: RenderJob, following: RenderJob) -> str:
    if following.chapter != current.chapter:
        return "chapter_change"
    if following.scene_id != current.scene_id:
        return "scene_change"
    return "dialogue" if current.text_type == "dialogue" else "narration"


def _frame_count(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes()
    except (EOFError, wave.Error) as error:
        raise ValueError(f"invalid WAV audio: {path}") from error


def _frames_to_ms(frames: int, sample_rate: int) -> int:
    return round(frames * 1000 / sample_rate)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
