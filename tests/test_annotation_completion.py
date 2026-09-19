from pathlib import Path

import pytest

from novel_tts.annotations import complete_annotation, load_annotation, save_annotation
from novel_tts.models import Annotation, ChapterLineRange, LineRange, Scene, Segment


def make_scenes() -> list[Scene]:
    return [
        Scene("S0001", [ChapterLineRange("001", LineRange(1, 2))], "第一场"),
        Scene("S0002", [ChapterLineRange("001", LineRange(3, 5))], "第二场"),
    ]


def test_complete_annotation_fills_gaps_and_splits_at_scene_boundaries() -> None:
    annotation = Annotation(1, [Segment(LineRange(2, 2), "小明", "dialogue", None)])

    completed = complete_annotation(annotation, 5, make_scenes())

    assert [
        (segment.line.format(), segment.name, segment.type) for segment in completed.segments
    ] == [
        (1, "NARRATOR", "narration"),
        (2, "小明", "dialogue"),
        ("3-5", "NARRATOR", "narration"),
    ]


def test_complete_annotation_is_idempotent_and_preserves_explicit_review() -> None:
    annotation = Annotation(
        1,
        [
            Segment(
                LineRange(2, 2),
                "UNKNOWN",
                "dialogue",
                None,
                review=True,
                review_reason="ambiguous_speaker",
            )
        ],
    )

    first = complete_annotation(annotation, 5, make_scenes())
    second = complete_annotation(first, 5, make_scenes())

    assert second == first
    assert second.segments[1].review is True
    assert second.segments[1].review_reason == "ambiguous_speaker"


@pytest.mark.parametrize(
    ("segments", "message"),
    [
        (
            [
                Segment(LineRange(1, 1), "小明", "dialogue", None),
                Segment(LineRange(1, 2), "小红", "dialogue", None),
            ],
            "overlaps or is out of order",
        ),
        ([Segment(LineRange(6, 6), "小明", "dialogue", None)], "exceeds chapter length"),
        ([Segment(LineRange(2, 3), "小明", "dialogue", None)], "outside or crosses scene ranges"),
    ],
)
def test_complete_annotation_rejects_invalid_explicit_segments(
    segments: list[Segment], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        complete_annotation(Annotation(1, segments), 5, make_scenes())


def test_complete_annotation_rejects_unmapped_gap() -> None:
    scenes = [Scene("S0001", [ChapterLineRange("001", LineRange(1, 2))], "第一场")]

    with pytest.raises(ValueError, match="outside or crosses scene ranges"):
        complete_annotation(Annotation(1, []), 3, scenes)


def test_missing_style_loads_as_none_and_is_omitted_on_save(tmp_path: Path) -> None:
    path = tmp_path / "001.yaml"
    path.write_text(
        "chapter: 1\nsegments:\n  - line: 1\n    name: 小明\n    type: dialogue\n",
        encoding="utf-8",
    )

    annotation = load_annotation(path)
    assert annotation.segments[0].style is None

    save_annotation(path, annotation)
    assert "style:" not in path.read_text(encoding="utf-8")
