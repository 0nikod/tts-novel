from pathlib import Path

from typer.testing import CliRunner

from novel_tts.annotations import load_annotation
from novel_tts.book import Book
from novel_tts.cli import app

runner = CliRunner()


def make_sparse_book(tmp_path: Path) -> Book:
    book = Book(tmp_path / "book")
    book.initialize()
    (book.source_dir / "001.txt").write_text("旁白。\n“你好。”\n结尾。\n", encoding="utf-8")
    (book.processed_dir / "001.txt").write_text(
        "1-旁白。\n2-“你好。”\n3-结尾。\n", encoding="utf-8"
    )
    book.persons_path.write_text(
        "persons:\n  - name: 小明\n    aliases: []\n    role: main\n", encoding="utf-8"
    )
    book.scenes_path.write_text(
        "scenes:\n  - id: S0001\n    line: '001:1-3'\n    summary: 测试场景\n",
        encoding="utf-8",
    )
    (book.annotations_dir / "001.yaml").write_text(
        "chapter: 1\nsegments:\n  - line: 2\n    name: 小明\n    type: dialogue\n",
        encoding="utf-8",
    )
    return book


def test_fill_annotations_cli_is_idempotent(tmp_path: Path) -> None:
    book = make_sparse_book(tmp_path)
    path = book.annotations_dir / "001.yaml"

    result = runner.invoke(app, ["fill-annotations", str(book.root), "--chapter", "001"])

    assert result.exit_code == 0, result.stdout
    annotation = load_annotation(path)
    assert [
        (segment.line.format(), segment.name, segment.type) for segment in annotation.segments
    ] == [
        (1, "NARRATOR", "narration"),
        (2, "小明", "dialogue"),
        (3, "NARRATOR", "narration"),
    ]

    first = path.read_bytes()
    second_result = runner.invoke(app, ["fill-annotations", str(book.root), "--chapter", "001"])

    assert second_result.exit_code == 0, second_result.stdout
    assert path.read_bytes() == first
    assert "added 0 narrator segment(s)" in second_result.stdout
