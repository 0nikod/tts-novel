from __future__ import annotations

from pathlib import Path
from typing import Any

from .annotation_schema import STYLE_SCHEMA, SYSTEM_NAMES
from .book import Book
from .persons import load_persons
from .preprocessing import read_processed


def build_agent_context(
    book: Book,
    chapter: str,
    *,
    previous_lines: int = 20,
    include_existing: bool = True,
) -> dict[str, Any]:
    if previous_lines < 0:
        raise ValueError("previous_lines must be non-negative")
    current_path = book.resolve_processed_chapter(chapter)
    current_stem = current_path.stem
    current = read_processed(current_path)
    people = load_persons(book.persons_path)
    mode = book.annotation_mode()

    processed = book.processed_chapters()
    current_index = next(index for index, path in enumerate(processed) if path == current_path)
    previous_chapter: str | None = None
    previous: list[dict[str, Any]] = []
    if previous_lines and current_index > 0:
        previous_path = processed[current_index - 1]
        previous_chapter = previous_path.stem
        previous = [
            {"line": line.number, "text": line.text}
            for line in read_processed(previous_path)[-previous_lines:]
        ]

    annotation_path = book.annotations_dir / f"{current_stem}.yaml"
    existing = None
    if include_existing and annotation_path.exists():
        existing = annotation_path.read_text(encoding="utf-8-sig").rstrip()

    return {
        "annotation": {
            "mode": mode,
            "default_explicit_type": "dialogue",
            "uncovered": "NARRATOR/narration",
        },
        "system_names": [
            {"name": name, "description": spec["description"]}
            for name, spec in SYSTEM_NAMES.items()
        ],
        "style": {field: spec["description"] for field, spec in STYLE_SCHEMA.items()},
        "persons": [person.name for person in people],
        "aliases": {alias: person.name for person in people for alias in person.aliases},
        "previous": {
            "chapter": previous_chapter,
            "lines": previous,
        },
        "current": {
            "chapter": current_stem,
            "lines": [{"line": line.number, "text": line.text} for line in current],
        },
        "existing": existing,
    }


def format_agent_context(context: dict[str, Any]) -> str:
    annotation = context["annotation"]
    output = [
        "[annotation]",
        f"mode: {annotation['mode']}",
        f"default_explicit_type: {annotation['default_explicit_type']}",
        f"uncovered: {annotation['uncovered']}",
        "",
        "[system-names]",
    ]
    output.extend(item["name"] for item in context["system_names"])
    output.extend(["", "[style]"])
    output.extend(f"{field}: {description}" for field, description in context["style"].items())
    output.extend(["", "[persons]"])
    output.extend(context["persons"] or ["(none)"])
    output.extend(["", "[aliases]"])
    aliases = context["aliases"]
    output.extend([f"{alias} -> {name}" for alias, name in aliases.items()] or ["(none)"])
    output.extend(["", "[previous]"])
    previous = context["previous"]
    if previous["chapter"] is None:
        output.append("(none)")
    else:
        output.append(f"chapter: {previous['chapter']}")
        output.extend(f"{line['line']}-{line['text']}" for line in previous["lines"])
    output.extend(["", "[current]"])
    output.extend(f"{line['line']}-{line['text']}" for line in context["current"]["lines"])
    output.extend(["", "[existing]"])
    output.append(context["existing"] if context["existing"] is not None else "(none)")
    return "\n".join(output) + "\n"


def context_reads_only_semantic_paths(book: Book) -> tuple[Path, ...]:
    """Document the intended ownership boundary for callers and tests."""
    return (
        book.config_path,
        book.persons_path,
        book.processed_dir,
        book.annotations_dir,
    )
