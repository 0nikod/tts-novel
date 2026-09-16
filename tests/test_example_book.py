from pathlib import Path

import pytest

from novel_tts.annotations import load_annotation
from novel_tts.book import Book
from novel_tts.preprocessing import format_processed, preprocess_text
from novel_tts.scenes import load_scenes
from novel_tts.validation import validate_book

EXAMPLE_BOOK = Path(__file__).resolve().parents[1] / "books" / "example-book"


@pytest.mark.parametrize(("chapter", "line_count"), [("01", 20), ("02", 173)])
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

    assert len(scenes) == 10
    assert scenes[0].line[0].format() == "01:1-5"
    assert scenes[-1].id == "S0010"
    assert scenes[-1].line[0].format() == "02:146-173"


def test_example_annotations_include_thought_style_and_review() -> None:
    first = load_annotation(EXAMPLE_BOOK / "annotations" / "01.yaml")
    second = load_annotation(EXAMPLE_BOOK / "annotations" / "02.yaml")

    first_reviews = [segment for segment in first.segments if segment.review]
    second_reviews = [segment for segment in second.segments if segment.review]
    thought = next(segment for segment in second.segments if segment.line.start == 84)
    styled = next(segment for segment in second.segments if segment.line.start == 129)

    assert len(first_reviews) == 1
    assert len(second_reviews) == 10
    assert all(segment.name == "UNKNOWN" for segment in first_reviews + second_reviews)
    assert all(
        segment.review_reason == "ambiguous_speaker" for segment in first_reviews + second_reviews
    )
    assert thought.name == "林冲"
    assert thought.type == "thought"
    assert styled.style is not None
    assert styled.style["delivery"] == "shout"
    assert styled.style["volume"] == "high"
