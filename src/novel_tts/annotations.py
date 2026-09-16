from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Annotation, LineRange, Segment, STYLE_FIELDS


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
            "annotation has unsupported fields: "
            + ", ".join(sorted(map(str, root_extra)))
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
        allowed = {
            "line", "name", "type", "style", "scene_id", "review", "review_reason"
        }
        extra = set(item) - allowed
        if extra:
            raise ValueError(
                f"segment {index} has unsupported fields: "
                + ", ".join(sorted(map(str, extra)))
            )
        required = ("line", "name", "type", "style", "scene_id")
        missing = [key for key in required if key not in item]
        if missing:
            raise ValueError(f"segment {index} missing: {', '.join(missing)}")
        try:
            lines = LineRange.parse(item["line"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"segment {index}: {error}") from error
        style = item["style"]
        if style is not None and not isinstance(style, dict):
            raise ValueError(f"segment {index}: style must be null or a mapping")
        if style is not None and any(not isinstance(key, str) for key in style):
            raise ValueError(f"segment {index}: style field names must be strings")
        review = item.get("review", False)
        if not isinstance(review, bool):
            raise ValueError(f"segment {index}: review must be boolean")
        for key in ("name", "type", "scene_id"):
            if not isinstance(item[key], str):
                raise ValueError(f"segment {index}: {key} must be a string")
        review_reason = item.get("review_reason")
        if review_reason is not None and not isinstance(review_reason, str):
            raise ValueError(f"segment {index}: review_reason must be a string")
        segments.append(
            Segment(
                line=lines,
                name=item["name"],
                type=item["type"],
                style=style,
                scene_id=item["scene_id"],
                review=review,
                review_reason=review_reason,
            )
        )
    return Annotation(chapter, segments)


def segment_to_dict(segment: Segment) -> dict[str, Any]:
    item: dict[str, Any] = {
        "line": segment.line.format(),
        "name": segment.name,
        "type": segment.type,
        "style": segment.style,
        "scene_id": segment.scene_id,
    }
    if segment.review:
        item["review"] = True
    if segment.review_reason is not None:
        item["review_reason"] = segment.review_reason
    return item


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
                scene_id=previous.scene_id,
                review=previous.review,
                review_reason=previous.review_reason,
            )
        else:
            merged.append(segment)
    return merged


def canonical_style(style: dict[str, str | None] | None) -> dict[str, str | None] | None:
    if style is None:
        return None
    return {field: style.get(field) for field in STYLE_FIELDS}
