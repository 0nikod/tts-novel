from pathlib import Path

from typer.testing import CliRunner

from novel_tts.book import Book
from novel_tts.cli import app

runner = CliRunner()


def test_inspect_materializes_without_modifying_annotation(tmp_path: Path) -> None:
    book = Book(tmp_path / "book")
    book.initialize()
    (book.source_dir / "001.txt").write_text("旁白\n“话”\n", encoding="utf-8")
    (book.processed_dir / "001.txt").write_text("1-旁白\n2-“话”\n", encoding="utf-8")
    book.persons_path.write_text("persons:\n  - name: 小明\n    aliases: []\n", encoding="utf-8")
    annotation = book.annotations_dir / "001.yaml"
    annotation.write_text("segments:\n  - line: 2\n    name: 小明\n", encoding="utf-8")
    before = annotation.read_bytes()

    result = runner.invoke(app, ["inspect", str(book.root), "--chapter", "1"])

    assert result.exit_code == 0, result.stdout
    assert "NARRATOR" in result.stdout
    assert "小明" in result.stdout
    assert annotation.read_bytes() == before


def test_removed_commands_are_not_exposed() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "fill-annotations" not in result.stdout
    render = runner.invoke(app, ["render", "--help"])
    assert "capabilities" not in render.stdout
    assert "providers" in render.stdout


def test_render_providers_lists_custom_and_mimo() -> None:
    result = runner.invoke(app, ["render", "providers"])
    assert result.exit_code == 0, result.stdout
    assert "custom: any model" in result.stdout
    assert "mimo-v2.5-tts" in result.stdout
