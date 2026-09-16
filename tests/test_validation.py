from pathlib import Path

from novel_tts.book import Book
from novel_tts.validation import validate_book


def make_book(tmp_path: Path) -> Book:
    book = Book(tmp_path / "book")
    book.initialize()
    (book.source_dir / "001.txt").write_text("旁白。\n“你好。”\n", encoding="utf-8")
    (book.processed_dir / "001.txt").write_text("1-旁白。\n2-“你好。”\n", encoding="utf-8")
    book.persons_path.write_text(
        "persons:\n  - name: 小明\n    aliases: []\n    role: main\n", encoding="utf-8"
    )
    book.scenes_path.write_text(
        "scenes:\n  - id: S0001\n    line: '001:1-2'\n    summary: 小明出现\n",
        encoding="utf-8",
    )
    (book.annotations_dir / "001.yaml").write_text(
        "chapter: 1\n"
        "segments:\n"
        "  - line: 1\n"
        "    name: NARRATOR\n"
        "    type: narration\n"
        "    style: null\n"
        "    scene_id: S0001\n"
        "  - line: 2\n"
        "    name: 小明\n"
        "    type: dialogue\n"
        "    style: null\n"
        "    scene_id: S0001\n",
        encoding="utf-8",
    )
    return book


def test_valid_book(tmp_path: Path) -> None:
    assert validate_book(make_book(tmp_path)) == []


def test_reports_gap_unknown_person_and_scene_mismatch(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    (book.annotations_dir / "001.yaml").write_text(
        "chapter: 1\n"
        "segments:\n"
        "  - line: 2\n"
        "    name: 路人\n"
        "    type: dialogue\n"
        "    style: null\n"
        "    scene_id: S9999\n",
        encoding="utf-8",
    )
    messages = [issue.message for issue in validate_book(book)]
    assert any("unknown person" in message for message in messages)
    assert any("missing scene" in message for message in messages)
    assert any("uncovered lines: 1" in message for message in messages)


def test_detects_scene_range_out_of_bounds(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    book.scenes_path.write_text(
        "scenes:\n  - id: S0001\n    line: '001:1-9'\n    summary: 错误范围\n",
        encoding="utf-8",
    )
    messages = [issue.message for issue in validate_book(book)]
    assert any("exceeds chapter length" in message for message in messages)
