from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .models import ChapterLineRange, Scene


SCENE_ID_RE = re.compile(r"^S(\d{4,})$")


def load_scenes(path: Path) -> list[Scene]:
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML: {error}") from error
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("scenes", []), list):
        raise ValueError("root must be a mapping containing a scenes list")
    scenes: list[Scene] = []
    for index, item in enumerate(data.get("scenes", []), 1):
        if not isinstance(item, dict):
            raise ValueError(f"scene {index} must be a mapping")
        extra = set(item) - {"id", "line", "summary"}
        if extra:
            raise ValueError(
                f"scene {index} has unsupported fields: "
                + ", ".join(sorted(map(str, extra)))
            )
        try:
            scene_id = item["id"]
            raw_line = item["line"]
            summary = item["summary"]
        except KeyError as error:
            raise ValueError(f"scene {index} is missing {error.args[0]}") from error
        raw_refs = raw_line if isinstance(raw_line, list) else [raw_line]
        try:
            refs = [ChapterLineRange.parse(value) for value in raw_refs]
        except (TypeError, ValueError) as error:
            raise ValueError(f"scene {index}: {error}") from error
        if not isinstance(scene_id, str) or not isinstance(summary, str):
            raise ValueError(f"scene {index}: id and summary must be strings")
        scenes.append(Scene(scene_id, refs, summary))
    return scenes


def scene_to_dict(scene: Scene) -> dict[str, Any]:
    ranges = [ref.format() for ref in scene.line]
    return {
        "id": scene.id,
        "line": ranges[0] if len(ranges) == 1 else ranges,
        "summary": scene.summary,
    }


def save_scenes(path: Path, scenes: list[Scene]) -> None:
    data = {"scenes": [scene_to_dict(scene) for scene in scenes]}
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )


def next_scene_id(scenes: list[Scene]) -> str:
    numbers = []
    for scene in scenes:
        match = SCENE_ID_RE.match(scene.id)
        if match:
            numbers.append(int(match.group(1)))
    return f"S{max(numbers, default=0) + 1:04d}"
