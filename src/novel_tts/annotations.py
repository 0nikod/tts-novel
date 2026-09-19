from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from .annotation_schema import STYLE_FIELDS, STYLE_TAG_FIELDS, TEXT_TYPES
from .models import Annotation, LineRange, ProcessedLine, Segment, Style


def load_annotation(path: Path) -> Annotation:
    """Load one sparse annotation file.

    The chapter comes exclusively from the filename. Missing segment fields use
    the canonical sparse defaults: dialogue, no style, and no review.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError(f"annotation does not exist: {path}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML: {error}") from error
    if data is None:
        data = {"segments": []}
    if not isinstance(data, dict):
        raise ValueError("annotation root must be a mapping")
    extra = set(data) - {"segments"}
    if extra:
        raise ValueError("annotation has unsupported fields: " + ", ".join(sorted(map(str, extra))))
    if not isinstance(data.get("segments"), list):
        raise ValueError("annotation requires a segments list")

    segments = [_load_segment(item, index) for index, item in enumerate(data["segments"], 1)]
    return Annotation(segments)


def _load_segment(item: Any, index: int) -> Segment:
    if not isinstance(item, dict):
        raise ValueError(f"segment {index} must be a mapping")
    allowed = {"line", "name", "type", "style", "review"}
    extra = set(item) - allowed
    if extra:
        raise ValueError(
            f"segment {index} has unsupported fields: " + ", ".join(sorted(map(str, extra)))
        )
    missing = {"line", "name"} - set(item)
    if missing:
        raise ValueError(f"segment {index} missing: {', '.join(sorted(missing))}")
    raw_line = item["line"]
    if isinstance(raw_line, str) and re.fullmatch(r"[1-9][0-9]*-[1-9][0-9]*", raw_line) is None:
        raise ValueError(f"segment {index}: line range must use start-end format")
    try:
        lines = LineRange.parse(raw_line)
    except (TypeError, ValueError) as error:
        raise ValueError(f"segment {index}: {error}") from error

    name = item["name"]
    text_type = item.get("type", "dialogue")
    review = item.get("review", False)
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"segment {index}: name must be a non-empty string")
    if not isinstance(text_type, str) or text_type not in TEXT_TYPES:
        allowed_types = ", ".join(TEXT_TYPES)
        raise ValueError(
            f"segment {index}: invalid type {text_type!r}; allowed values: {allowed_types}"
        )
    if not isinstance(review, bool):
        raise ValueError(f"segment {index}: review must be boolean")
    if "style" in item and item["style"] is None:
        raise ValueError(f"segment {index}: omit style instead of using null")
    style = _load_style(item.get("style"), index)
    return Segment(lines, name, text_type, style, review)


def _load_style(value: Any, index: int) -> Style | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"segment {index}: style must be null or a mapping")
    if not value:
        raise ValueError(f"segment {index}: style must contain at least one field")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"segment {index}: style field names must be strings")
    unknown = set(value) - set(STYLE_FIELDS)
    if unknown:
        raise ValueError(
            f"segment {index}: unsupported style fields: " + ", ".join(sorted(unknown))
        )
    style: Style = {}
    for field in STYLE_FIELDS:
        if field not in value:
            continue
        style_value = value[field]
        if field in STYLE_TAG_FIELDS:
            style[field] = _load_tags(style_value, index, field)
            continue
        if not isinstance(style_value, str) or not style_value.strip():
            raise ValueError(f"segment {index}: style.{field} must be a non-empty string")
        style[field] = style_value
    return style


def _load_tags(value: Any, index: int, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"segment {index}: style.{field} must be a non-empty list")
    if any(not isinstance(tag, str) or not tag.strip() for tag in value):
        raise ValueError(f"segment {index}: style.{field} items must be non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"segment {index}: style.{field} must not contain duplicates")
    return list(value)


def segment_to_dict(segment: Segment, *, include_defaults: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {"line": segment.line.format(), "name": segment.name}
    if include_defaults or segment.type != "dialogue":
        item["type"] = segment.type
    if segment.style is not None:
        item["style"] = segment.style
    if segment.review:
        item["review"] = True
    elif include_defaults:
        item["review"] = False
    return item


def annotation_to_data(annotation: Annotation, *, include_defaults: bool = False) -> dict[str, Any]:
    return {
        "segments": [
            segment_to_dict(segment, include_defaults=include_defaults)
            for segment in annotation.segments
        ]
    }


def dump_annotation(annotation: Annotation, *, include_defaults: bool = False) -> str:
    return yaml.safe_dump(
        annotation_to_data(annotation, include_defaults=include_defaults),
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    )


def save_annotation(path: Path, annotation: Annotation) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_annotation(annotation), encoding="utf-8")


def materialize_annotation(
    processed_lines: Sequence[ProcessedLine],
    sparse_segments: Sequence[Segment],
) -> list[Segment]:
    """Fill sparse gaps with narrator segments without modifying canonical YAML."""
    numbers = [line.number for line in processed_lines]
    if numbers != list(range(1, len(processed_lines) + 1)):
        raise ValueError("processed line numbers must be continuous from 1")
    line_count = len(processed_lines)
    previous_end = 0
    for index, segment in enumerate(sparse_segments, 1):
        if segment.line.end > line_count:
            raise ValueError(
                f"segment {index} ({segment.line.format()}) exceeds chapter length {line_count}"
            )
        if segment.line.start <= previous_end:
            raise ValueError(
                f"segment {index} ({segment.line.format()}) overlaps or is out of order"
            )
        previous_end = segment.line.end

    effective: list[Segment] = []
    cursor = 1
    for segment in sparse_segments:
        if cursor < segment.line.start:
            effective.append(Segment.narrator(LineRange(cursor, segment.line.start - 1)))
        effective.append(segment)
        cursor = segment.line.end + 1
    if cursor <= line_count:
        effective.append(Segment.narrator(LineRange(cursor, line_count)))
    return merge_adjacent_segments(effective)


def merge_adjacent_segments(segments: Sequence[Segment]) -> list[Segment]:
    merged: list[Segment] = []
    for segment in segments:
        if (
            merged
            and merged[-1].line.end + 1 == segment.line.start
            and merged[-1].merge_key() == segment.merge_key()
        ):
            previous = merged[-1]
            merged[-1] = Segment(
                LineRange(previous.line.start, segment.line.end),
                previous.name,
                previous.type,
                previous.style,
                previous.review,
            )
        else:
            merged.append(segment)
    return merged
