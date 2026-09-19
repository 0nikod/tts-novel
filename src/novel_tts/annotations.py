from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from .annotation_schema import NARRATOR_NAME, REVIEW_REASONS, STYLE_FIELDS, STYLE_VALUES, TEXT_TYPES
from .models import Annotation, LineRange, ReviewReason, Scene, Segment, TextType
from .scenes import find_scene


def load_annotation(path: Path) -> Annotation:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("annotation root must be a mapping")
    root_extra = set(data) - {"chapter", "segments"}
    if root_extra:
        raise ValueError(
            "annotation has unsupported fields: " + ", ".join(sorted(map(str, root_extra)))
        )
    if "chapter" not in data or "segments" not in data:
        raise ValueError("annotation requires chapter and segments")
    chapter = data["chapter"]
    if isinstance(chapter, bool) or not isinstance(chapter, (int, str)):
        raise ValueError("chapter must be an integer or numeric string")
    if not str(chapter).isdigit():
        raise ValueError("chapter must be numeric")
    if not isinstance(data["segments"], list):
        raise ValueError("segments must be a list")

    segments: list[Segment] = []
    for index, item in enumerate(data["segments"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"segment {index} must be a mapping")
        allowed = {"line", "name", "type", "style", "review", "review_reason"}
        extra = set(item) - allowed
        if extra:
            raise ValueError(
                f"segment {index} has unsupported fields: " + ", ".join(sorted(map(str, extra)))
            )
        required = ("line", "name", "type")
        missing = [key for key in required if key not in item]
        if missing:
            raise ValueError(f"segment {index} missing: {', '.join(missing)}")
        try:
            lines = LineRange.parse(item["line"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"segment {index}: {error}") from error
        style = item.get("style")
        if style is not None and not isinstance(style, dict):
            raise ValueError(f"segment {index}: style must be null or a mapping")
        if style is not None:
            if not style:
                raise ValueError(f"segment {index}: style must contain at least one field")
            if any(not isinstance(key, str) for key in style):
                raise ValueError(f"segment {index}: style field names must be strings")
            unknown_style_fields = set(style) - set(STYLE_FIELDS)
            if unknown_style_fields:
                names = ", ".join(sorted(map(str, unknown_style_fields)))
                raise ValueError(f"segment {index}: unsupported style fields: {names}")
            for field, value in style.items():
                if not isinstance(value, str):
                    raise ValueError(f"segment {index}: style.{field} must be a string")
                if value not in STYLE_VALUES[field]:
                    allowed = ", ".join(STYLE_VALUES[field])
                    raise ValueError(
                        f"segment {index}: invalid style.{field} value {value!r}; "
                        f"allowed values: {allowed}"
                    )
        review = item.get("review", False)
        if not isinstance(review, bool):
            raise ValueError(f"segment {index}: review must be boolean")
        for key in ("name", "type"):
            if not isinstance(item[key], str):
                raise ValueError(f"segment {index}: {key} must be a string")
        if item["type"] not in TEXT_TYPES:
            allowed_types = ", ".join(TEXT_TYPES)
            raise ValueError(
                f"segment {index}: invalid type {item['type']!r}; allowed values: {allowed_types}"
            )
        review_reason = item.get("review_reason")
        if review_reason is not None:
            if not isinstance(review_reason, str):
                raise ValueError(f"segment {index}: review_reason must be a string")
            if review_reason not in REVIEW_REASONS:
                allowed_reasons = ", ".join(REVIEW_REASONS)
                raise ValueError(
                    f"segment {index}: invalid review_reason {review_reason!r}; "
                    f"allowed values: {allowed_reasons}"
                )
        segments.append(
            Segment(
                line=lines,
                name=item["name"],
                type=cast("TextType", item["type"]),
                style=style,
                review=review,
                review_reason=cast("ReviewReason | None", review_reason),
            )
        )
    return Annotation(chapter, segments)


def segment_to_dict(segment: Segment) -> dict[str, Any]:
    item: dict[str, Any] = {
        "line": segment.line.format(),
        "name": segment.name,
        "type": segment.type,
    }
    if segment.style is not None:
        item["style"] = segment.style
    if segment.review:
        item["review"] = True
    if segment.review_reason is not None:
        item["review_reason"] = segment.review_reason
    return item


def complete_annotation(
    annotation: Annotation,
    line_count: int,
    scenes: list[Scene],
) -> Annotation:
    """Fill uncovered lines with narrator narration segments.

    Explicit segments are preserved in their original order. Every explicit and
    generated segment must fit wholly within one scene from ``scenes.yaml``.
    """
    if line_count < 0:
        raise ValueError("line_count must not be negative")

    previous_end = 0
    for index, segment in enumerate(annotation.segments, 1):
        if segment.line.end > line_count:
            raise ValueError(
                f"segment {index} ({segment.line.format()}) exceeds chapter length {line_count}"
            )
        if segment.line.start <= previous_end:
            raise ValueError(
                f"segment {index} ({segment.line.format()}) overlaps or is out of order"
            )
        if find_scene(scenes, annotation.chapter, segment.line) is None:
            raise ValueError(
                f"segment {index} ({segment.line.format()}) is outside or crosses scene ranges"
            )
        previous_end = segment.line.end

    completed: list[Segment] = []
    cursor = 1
    for segment in annotation.segments:
        if cursor < segment.line.start:
            completed.extend(
                _narrator_segments(
                    annotation.chapter,
                    LineRange(cursor, segment.line.start - 1),
                    scenes,
                )
            )
        completed.append(segment)
        cursor = segment.line.end + 1
    if cursor <= line_count:
        completed.extend(
            _narrator_segments(annotation.chapter, LineRange(cursor, line_count), scenes)
        )
    return Annotation(annotation.chapter, completed)


def _narrator_segments(
    chapter: int | str,
    lines: LineRange,
    scenes: list[Scene],
) -> list[Segment]:
    generated: list[Segment] = []
    start = lines.start
    current_scene = find_scene(scenes, chapter, LineRange(start, start))
    if current_scene is None:
        raise ValueError(f"line {start} is outside or crosses scene ranges")
    for number in range(start + 1, lines.end + 1):
        scene = find_scene(scenes, chapter, LineRange(number, number))
        if scene is None:
            raise ValueError(f"line {number} is outside or crosses scene ranges")
        if scene.id != current_scene.id:
            generated.append(
                Segment(LineRange(start, number - 1), NARRATOR_NAME, "narration", None)
            )
            start = number
            current_scene = scene
    generated.append(Segment(LineRange(start, lines.end), NARRATOR_NAME, "narration", None))
    return generated


def save_annotation(path: Path, annotation: Annotation) -> None:
    data = {
        "chapter": annotation.chapter,
        "segments": [segment_to_dict(segment) for segment in annotation.segments],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )


def merge_adjacent_segments(segments: list[Segment]) -> list[Segment]:
    merged: list[Segment] = []
    for segment in segments:
        if (
            merged
            and merged[-1].line.end + 1 == segment.line.start
            and merged[-1].merge_key() == segment.merge_key()
        ):
            previous = merged[-1]
            merged[-1] = Segment(
                line=LineRange(previous.line.start, segment.line.end),
                name=previous.name,
                type=previous.type,
                style=previous.style,
                review=previous.review,
                review_reason=previous.review_reason,
            )
        else:
            merged.append(segment)
    return merged


def canonical_style(style: dict[str, str] | None) -> dict[str, str] | None:
    if style is None:
        return None
    return dict(style)
