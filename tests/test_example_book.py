from pathlib import Path

import pytest

from novel_tts.annotations import load_annotation
from novel_tts.book import Book
from novel_tts.preprocessing import format_processed, preprocess_text
from novel_tts.scenes import load_scenes
from novel_tts.validation import validate_book

EXAMPLE_BOOK = Path(__file__).resolve().parents[1] / "books" / "example-book"


@pytest.mark.parametrize("chapter", ["001", "002"])
def test_example_processed_text_can_be_reproduced(chapter: str) -> None:
    source = (EXAMPLE_BOOK / "source" / f"{chapter}.txt").read_text(encoding="utf-8")
    committed = (EXAMPLE_BOOK / "processed" / f"{chapter}.txt").read_text(encoding="utf-8")

    result = preprocess_text(source)

    assert result.warnings == []
    assert format_processed(result.lines) == committed


def test_example_book_passes_structural_validation() -> None:
    assert validate_book(Book(EXAMPLE_BOOK)) == []


def test_example_contains_cross_chapter_scene_and_review_item() -> None:
    scenes = load_scenes(EXAMPLE_BOOK / "scenes.yaml")
    assert [line.format() for line in scenes[0].line] == ["001:1-6", "002:1-6"]

    annotation = load_annotation(EXAMPLE_BOOK / "annotations" / "002.yaml")
    review_segments = [segment for segment in annotation.segments if segment.review]

    assert len(review_segments) == 1
    assert review_segments[0].line.format() == 13
    assert review_segments[0].name == "UNKNOWN"
    assert review_segments[0].review_reason == "unknown_character"
