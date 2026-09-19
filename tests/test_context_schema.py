import json
from pathlib import Path

from novel_tts.book import Book
from novel_tts.context import build_agent_context, format_agent_context
from novel_tts.schema_codegen import render_annotation_schema

ROOT = Path(__file__).parents[1]


def make_book(tmp_path: Path) -> Book:
    book = Book(tmp_path / "book")
    book.initialize()
    for stem in ("001", "002"):
        (book.source_dir / f"{stem}.txt").write_text("text\n", encoding="utf-8")
    (book.processed_dir / "001.txt").write_text("1-one\n2-two\n3-three\n", encoding="utf-8")
    (book.processed_dir / "002.txt").write_text("1-current\n", encoding="utf-8")
    book.persons_path.write_text(
        "persons:\n  - name: 小明\n    aliases:\n      - 明明\n", encoding="utf-8"
    )
    (book.annotations_dir / "002.yaml").write_text(
        "segments:\n  - line: 1\n    name: 小明\n", encoding="utf-8"
    )
    book.scenes_path.write_text("this: is not read\n", encoding="utf-8")
    (book.render_dir / "config.yaml").write_text("this: is not read\n", encoding="utf-8")
    return book


def test_generated_annotation_schema_is_current() -> None:
    committed = (ROOT / "docs" / "annotation.schema.yaml").read_text(encoding="utf-8")
    assert render_annotation_schema() == committed
    assert committed.startswith("# Generated from src/novel_tts/annotation_schema.py.")
    assert "chapter:" not in committed
    assert "review_reason" not in committed


def test_agent_context_is_bounded_and_complete(tmp_path: Path) -> None:
    context = build_agent_context(make_book(tmp_path), "2", previous_lines=2)
    text = format_agent_context(context)

    assert context["annotation"]["mode"] == "dialogue"
    assert [item["name"] for item in context["system_names"]] == [
        "NARRATOR",
        "UNKNOWN",
        "EXTRA",
        "EXTRA_MALE",
        "EXTRA_FEMALE",
    ]
    assert context["previous"]["lines"] == [
        {"line": 2, "text": "two"},
        {"line": 3, "text": "three"},
    ]
    assert context["current"]["lines"] == [{"line": 1, "text": "current"}]
    assert context["aliases"] == {"明明": "小明"}
    assert "name: 小明" in context["existing"]
    assert "[style]" in text
    json.dumps(context, ensure_ascii=False)
