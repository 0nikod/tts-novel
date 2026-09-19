from pathlib import Path

import pytest

from novel_tts.annotations import load_annotation, materialize_annotation, save_annotation
from novel_tts.book import Book
from novel_tts.models import LineRange, Person, ProcessedLine, Segment
from novel_tts.persons import alias_map, load_persons, save_persons
from novel_tts.validation import validate_annotations


def processed(count: int) -> list[ProcessedLine]:
    return [ProcessedLine(number, f"text {number}") for number in range(1, count + 1)]


def test_sparse_defaults_and_canonical_save(tmp_path: Path) -> None:
    path = tmp_path / "001.yaml"
    path.write_text(
        "segments:\n  - line: 2\n    name: 小明\n  - line: 4\n    name: 小明\n    type: thought\n",
        encoding="utf-8",
    )

    annotation = load_annotation(path)

    assert annotation.segments[0].type == "dialogue"
    assert annotation.segments[0].style is None
    assert annotation.segments[0].review is False
    save_annotation(path, annotation)
    content = path.read_text(encoding="utf-8")
    assert "chapter:" not in content
    assert "type: dialogue" not in content
    assert "style: null" not in content
    assert "type: thought" in content


def test_freeform_style_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "001.yaml"
    path.write_text(
        "segments:\n"
        "  - line: 2\n"
        "    name: 小明\n"
        "    style:\n"
        "      direction: |-\n"
        "        低声、迟疑，后半句逐渐疲惫。\n"
        "      tags_before: [紧张, 深呼吸]\n"
        "      tags_after: [苦笑]\n",
        encoding="utf-8",
    )

    annotation = load_annotation(path)

    assert annotation.segments[0].style == {
        "direction": "低声、迟疑，后半句逐渐疲惫。",
        "tags_before": ["紧张", "深呼吸"],
        "tags_after": ["苦笑"],
    }
    save_annotation(path, annotation)
    assert load_annotation(path) == annotation


@pytest.mark.parametrize(
    ("style", "message"),
    [
        ("direction: ''", "style.direction must be a non-empty string"),
        ("tags_before: []", "style.tags_before must be a non-empty list"),
        ("tags_after: [苦笑, 苦笑]", "style.tags_after must not contain duplicates"),
        ("emotion: sad", "unsupported style fields: emotion"),
    ],
)
def test_invalid_freeform_style_is_rejected(tmp_path: Path, style: str, message: str) -> None:
    path = tmp_path / "001.yaml"
    path.write_text(
        f"segments:\n  - line: 1\n    name: 小明\n    style:\n      {style}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=message):
        load_annotation(path)


def test_old_chapter_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "001.yaml"
    path.write_text("chapter: 1\nsegments: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported fields: chapter"):
        load_annotation(path)


def test_explicit_null_style_is_not_canonical(tmp_path: Path) -> None:
    path = tmp_path / "001.yaml"
    path.write_text(
        "segments:\n  - line: 1\n    name: 小明\n    style: null\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="omit style"):
        load_annotation(path)


def test_materialize_empty_and_sparse_annotation() -> None:
    assert materialize_annotation(processed(3), []) == [
        Segment(LineRange(1, 3), "NARRATOR", "narration")
    ]

    effective = materialize_annotation(
        processed(6),
        [
            Segment(LineRange(2, 2), "小明"),
            Segment(LineRange(4, 5), "NARRATOR", "narration", {"direction": "缓慢朗读。"}),
        ],
    )
    assert [(item.line.format(), item.name, item.type, item.style) for item in effective] == [
        (1, "NARRATOR", "narration", None),
        (2, "小明", "dialogue", None),
        (3, "NARRATOR", "narration", None),
        ("4-5", "NARRATOR", "narration", {"direction": "缓慢朗读。"}),
        (6, "NARRATOR", "narration", None),
    ]


def make_book(
    tmp_path: Path, *, mode: str | None = None, annotation: str = "segments: []\n"
) -> Book:
    book = Book(tmp_path / "book")
    book.initialize()
    (book.source_dir / "001.txt").write_text("正文\n", encoding="utf-8")
    (book.processed_dir / "001.txt").write_text("1-正文\n", encoding="utf-8")
    book.persons_path.write_text(
        "persons:\n  - name: 小明\n    aliases:\n      - 明明\n", encoding="utf-8"
    )
    (book.annotations_dir / "001.yaml").write_text(annotation, encoding="utf-8")
    if mode:
        book.config_path.write_text(f"annotation:\n  mode: {mode}\n", encoding="utf-8")
    return book


def test_thought_mode_and_review_rules(tmp_path: Path) -> None:
    dialogue_book = make_book(
        tmp_path / "dialogue",
        annotation="segments:\n  - line: 1\n    name: 小明\n    type: thought\n",
    )
    assert any(
        "not allowed in dialogue mode" in issue.message
        for issue in validate_annotations(dialogue_book)
    )

    thought_book = make_book(
        tmp_path / "thought",
        mode="thought",
        annotation="segments:\n  - line: 1\n    name: UNKNOWN\n    type: thought\n",
    )
    assert any(
        "without review: true" in issue.message for issue in validate_annotations(thought_book)
    )
    path = thought_book.annotations_dir / "001.yaml"
    path.write_text(
        "segments:\n  - line: 1\n    name: UNKNOWN\n    type: thought\n    review: true\n",
        encoding="utf-8",
    )
    assert validate_annotations(thought_book) == []


@pytest.mark.parametrize("name", ["EXTRA", "EXTRA_MALE", "EXTRA_FEMALE"])
def test_extra_names_do_not_require_review(tmp_path: Path, name: str) -> None:
    book = make_book(
        tmp_path,
        annotation=f"segments:\n  - line: 1\n    name: {name}\n",
    )
    assert validate_annotations(book) == []


def test_person_round_trip_has_only_name_and_aliases(tmp_path: Path) -> None:
    path = tmp_path / "persons.yaml"
    people = [Person("小明", ["明明"])]
    save_persons(path, people)
    assert load_persons(path) == people
    assert alias_map(people) == {"明明": "小明"}
    assert "role" not in path.read_text(encoding="utf-8")
