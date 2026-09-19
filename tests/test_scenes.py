from pathlib import Path

from novel_tts.book import Book
from novel_tts.models import ChapterLineRange, LineRange, Scene
from novel_tts.scenes import split_range_at_scenes
from novel_tts.validation import validate_annotations, validate_scenes


def test_annotations_do_not_require_scenes(tmp_path: Path) -> None:
    book = Book(tmp_path / "book")
    book.initialize()
    (book.source_dir / "001.txt").write_text("text\n", encoding="utf-8")
    (book.processed_dir / "001.txt").write_text("1-text\n", encoding="utf-8")
    (book.annotations_dir / "001.yaml").write_text("segments: []\n", encoding="utf-8")
    assert not book.scenes_path.exists()
    assert validate_annotations(book) == []
    assert validate_scenes(book) == []


def test_runtime_scene_split_does_not_change_annotation_range() -> None:
    scenes = [
        Scene("A", [ChapterLineRange("001", LineRange(1, 2))], "a"),
        Scene("B", [ChapterLineRange("001", LineRange(3, 4))], "b"),
    ]
    assert split_range_at_scenes(scenes, "001", LineRange(1, 5)) == [
        (LineRange(1, 2), "A"),
        (LineRange(3, 4), "B"),
        (LineRange(5, 5), None),
    ]
