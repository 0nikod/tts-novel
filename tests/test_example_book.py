from pathlib import Path

from novel_tts.annotations import load_annotation
from novel_tts.book import Book
from novel_tts.renderer.planner import build_render_plan
from novel_tts.validation import validate_book

EXAMPLE = Path(__file__).parents[1] / "books" / "example-book"


def test_example_book_is_sparse_and_valid() -> None:
    assert validate_book(Book(EXAMPLE)) == []
    first = load_annotation(EXAMPLE / "annotations" / "01.yaml")
    second = load_annotation(EXAMPLE / "annotations" / "02.yaml")
    segments = first.segments + second.segments
    assert len(segments) == 37
    assert all(not (item.name == "NARRATOR" and item.type == "narration") for item in segments)
    assert all(item.type == "dialogue" for item in segments)


def test_example_book_builds_scene_optional_mimo_plan() -> None:
    book = Book(EXAMPLE)
    plan, _ = build_render_plan(book)
    assert plan.errors == []
    assert plan.jobs
