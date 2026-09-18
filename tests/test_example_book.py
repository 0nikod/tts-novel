from pathlib import Path

import pytest

from novel_tts.annotations import load_annotation
from novel_tts.book import Book
from novel_tts.preprocessing import format_processed, preprocess_text
from novel_tts.scenes import load_scenes
from novel_tts.validation import validate_book

EXAMPLE_BOOK = Path(__file__).resolve().parents[1] / "books" / "example-book"


@pytest.mark.parametrize(("chapter", "line_count"), [("01", 44), ("02", 36)])
def test_example_processed_text_can_be_reproduced(chapter: str, line_count: int) -> None:
    source = (EXAMPLE_BOOK / "source" / f"{chapter}.txt").read_text(encoding="utf-8")
    committed = (EXAMPLE_BOOK / "processed" / f"{chapter}.txt").read_text(encoding="utf-8")

    result = preprocess_text(source)

    assert result.warnings == []
    assert len(result.lines) == line_count
    assert format_processed(result.lines) == committed


def test_example_book_passes_structural_validation() -> None:
    assert validate_book(Book(EXAMPLE_BOOK)) == []


def test_example_scenes_cover_the_new_story() -> None:
    scenes = load_scenes(EXAMPLE_BOOK / "scenes.yaml")

    assert len(scenes) == 9
    assert scenes[0].line[0].format() == "01:1-3"
    assert scenes[-1].id == "S0009"
    assert scenes[-1].line[0].format() == "02:31-36"


def test_example_annotations_include_style_and_extra_fallback() -> None:
    first = load_annotation(EXAMPLE_BOOK / "annotations" / "01.yaml")
    second = load_annotation(EXAMPLE_BOOK / "annotations" / "02.yaml")

    all_segments = first.segments + second.segments
    first_extra_lines = {
        segment.line.start for segment in first.segments if segment.name == "EXTRA"
    }
    second_extra_lines = {
        segment.line.start for segment in second.segments if segment.name == "EXTRA"
    }
    styled = next(segment for segment in first.segments if segment.line.start == 11)
    narrator_dialogue = next(segment for segment in first.segments if segment.line.start == 35)

    assert not any(segment.review for segment in all_segments)
    assert not any(segment.name == "UNKNOWN" for segment in all_segments)
    assert {7, 11, 14, 24, 26} <= first_extra_lines
    assert {4, 7, 9, 11, 13} <= second_extra_lines
    assert narrator_dialogue.name == "酒店伙计"
    assert narrator_dialogue.type == "dialogue"
    assert styled.style is not None
    assert styled.style["delivery"] == "shout"
    assert styled.style["volume"] == "high"
