from pathlib import Path

import pytest

from novel_tts.annotations import load_annotation, merge_adjacent_segments, save_annotation
from novel_tts.models import Annotation, ChapterLineRange, LineRange, Scene, Segment
from novel_tts.scenes import find_scene, load_scenes, next_scene_id, save_scenes


def test_scene_round_trip_and_next_id(tmp_path: Path) -> None:
    path = tmp_path / "scenes.yaml"
    scenes = [
        Scene(
            "S0001",
            [ChapterLineRange("001", LineRange(1, 8)), ChapterLineRange("002", LineRange(1, 2))],
            "连续事件",
        )
    ]
    save_scenes(path, scenes)
    assert load_scenes(path) == scenes
    assert next_scene_id(scenes) == "S0002"


def test_find_scene_requires_the_complete_range_to_be_in_one_scene() -> None:
    scenes = [
        Scene("S0001", [ChapterLineRange("001", LineRange(1, 2))], "first"),
        Scene("S0002", [ChapterLineRange("001", LineRange(3, 4))], "second"),
        Scene(
            "S0003",
            [ChapterLineRange("001", LineRange(5, 5)), ChapterLineRange("002", LineRange(1, 1))],
            "cross chapter",
        ),
    ]

    assert find_scene(scenes, "001", LineRange(1, 2)).id == "S0001"
    assert find_scene(scenes, "002", LineRange(1, 1)).id == "S0003"
    assert find_scene(scenes, "001", LineRange(2, 3)) is None
    assert find_scene(scenes, "001", LineRange(9, 9)) is None


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("type: speech", "invalid type 'speech'"),
        ("review_reason: uncertain", "invalid review_reason 'uncertain'"),
        ("style:\n      mood: sad", "unsupported style fields: mood"),
        ("style:\n      emotion: furious", "invalid style.emotion value 'furious'"),
        ("style:\n      emotion: []", "style.emotion must be a string"),
        ("style:\n      emotion: null", "style.emotion must be a string"),
        ("style: {}", "style must contain at least one field"),
    ],
)
def test_load_annotation_rejects_values_outside_canonical_schema(
    tmp_path: Path, replacement: str, message: str
) -> None:
    path = tmp_path / "annotations.yaml"
    if replacement.startswith("type:"):
        type_line = replacement
        review_line = ""
        style_lines = "    style: null\n"
    elif replacement.startswith("review_reason:"):
        type_line = "type: dialogue"
        review_line = f"    review: true\n    {replacement}\n"
        style_lines = "    style: null\n"
    else:
        type_line = "type: dialogue"
        review_line = ""
        style_lines = f"    {replacement}\n"
    path.write_text(
        "chapter: 1\n"
        "segments:\n"
        "  - line: 1\n"
        "    name: 小明\n"
        f"    {type_line}\n"
        f"{style_lines}"
        f"{review_line}",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_annotation(path)


def test_annotation_rejects_scene_id_and_save_omits_it(tmp_path: Path) -> None:
    path = tmp_path / "annotations.yaml"
    path.write_text(
        "chapter: 1\n"
        "segments:\n"
        "  - line: 1\n"
        "    name: 小明\n"
        "    type: dialogue\n"
        "    style: null\n"
        "    scene_id: S0001\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported fields: scene_id"):
        load_annotation(path)

    annotation = Annotation(1, [Segment(LineRange(1, 1), "小明", "dialogue", None)])
    save_annotation(path, annotation)
    assert "scene_id" not in path.read_text(encoding="utf-8")


def test_merge_adjacent_segments() -> None:
    one = Segment(LineRange(1, 1), "小明", "dialogue", None)
    two = Segment(LineRange(2, 3), "小明", "dialogue", None)
    three = Segment(LineRange(4, 4), "小红", "dialogue", None)
    merged = merge_adjacent_segments([one, two, three])
    assert [segment.line for segment in merged] == [LineRange(1, 3), LineRange(4, 4)]
