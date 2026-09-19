from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .models import ChapterLineRange, LineRange, Scene


def load_scenes(path: Path) -> list[Scene]:
    """Load optional scene metadata. A missing file means no scene metadata."""
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML: {error}") from error
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        raise ValueError("root must be a mapping containing a scenes list")
    extra = set(data) - {"scenes"}
    if extra:
        raise ValueError("scenes root has unsupported fields: " + ", ".join(sorted(extra)))

    scenes: list[Scene] = []
    for index, item in enumerate(data["scenes"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"scene {index} must be a mapping")
        extra = set(item) - {"id", "line", "summary"}
        if extra:
            raise ValueError(
                f"scene {index} has unsupported fields: " + ", ".join(sorted(map(str, extra)))
            )
        missing = {"id", "line", "summary"} - set(item)
        if missing:
            raise ValueError(f"scene {index} is missing {', '.join(sorted(missing))}")
        scene_id = item["id"]
        summary = item["summary"]
        raw_line = item["line"]
        if not isinstance(scene_id, str) or not scene_id.strip():
            raise ValueError(f"scene {index}: id must be a non-empty string")
        if not isinstance(summary, str):
            raise ValueError(f"scene {index}: summary must be a string")
        raw_references = raw_line if isinstance(raw_line, list) else [raw_line]
        if not raw_references:
            raise ValueError(f"scene {index}: line must not be empty")
        try:
            references = [ChapterLineRange.parse(value) for value in raw_references]
        except (TypeError, ValueError) as error:
            raise ValueError(f"scene {index}: {error}") from error
        scenes.append(Scene(scene_id, references, summary))
    return scenes


def find_scene(scenes: Iterable[Scene], chapter: str | int, lines: LineRange) -> Scene | None:
    matches = [scene for scene in scenes if scene.covers(chapter, lines)]
    return matches[0] if len(matches) == 1 else None


def scene_at(scenes: Iterable[Scene], chapter: str | int, line: int) -> Scene | None:
    return find_scene(scenes, chapter, LineRange(line, line))


def split_range_at_scenes(
    scenes: Iterable[Scene], chapter: str | int, lines: LineRange
) -> list[tuple[LineRange, str | None]]:
    """Split a range only for runtime jobs; canonical annotations remain unchanged."""
    scene_list = list(scenes)
    boundaries = {lines.start, lines.end + 1}
    for scene in scene_list:
        for reference in scene.line:
            if int(reference.chapter) != int(chapter):
                continue
            if lines.start < reference.lines.start <= lines.end:
                boundaries.add(reference.lines.start)
            boundary = reference.lines.end + 1
            if lines.start < boundary <= lines.end:
                boundaries.add(boundary)
    ordered = sorted(boundaries)
    pieces: list[tuple[LineRange, str | None]] = []
    for start, next_start in zip(ordered, ordered[1:], strict=False):
        piece = LineRange(start, next_start - 1)
        scene = find_scene(scene_list, chapter, piece)
        scene_id = scene.id if scene is not None else None
        if pieces and pieces[-1][1] == scene_id and pieces[-1][0].end + 1 == piece.start:
            previous, _ = pieces[-1]
            pieces[-1] = (LineRange(previous.start, piece.end), scene_id)
        else:
            pieces.append((piece, scene_id))
    return pieces


def scene_to_dict(scene: Scene) -> dict[str, Any]:
    ranges = [reference.format() for reference in scene.line]
    return {
        "id": scene.id,
        "line": ranges[0] if len(ranges) == 1 else ranges,
        "summary": scene.summary,
    }


def save_scenes(path: Path, scenes: list[Scene]) -> None:
    path.write_text(
        yaml.safe_dump(
            {"scenes": [scene_to_dict(scene) for scene in scenes]},
            allow_unicode=True,
            sort_keys=False,
            width=1000,
        ),
        encoding="utf-8",
    )


def next_scene_id(scenes: list[Scene]) -> str:
    numbers = [
        int(scene.id[1:]) for scene in scenes if scene.id.startswith("S") and scene.id[1:].isdigit()
    ]
    return f"S{max(numbers, default=0) + 1:04d}"
