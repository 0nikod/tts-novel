from __future__ import annotations

from collections import Counter
from contextlib import suppress
from pathlib import Path

from .annotation_schema import SYSTEM_NAMES, UNKNOWN_NAME, allowed_text_types
from .annotations import load_annotation
from .book import Book
from .models import ValidationIssue
from .persons import load_persons
from .preprocessing import read_processed
from .scenes import load_scenes


def validate_annotations(book: Book, chapter: str | None = None) -> list[ValidationIssue]:
    """Validate processed text, people, mode, and sparse annotations only."""
    issues: list[ValidationIssue] = []
    try:
        source_chapters = book.source_chapters()
    except ValueError as error:
        return [_error(book.source_dir, str(error))]

    if chapter is not None:
        if not chapter.isdigit():
            return [_error(book.source_dir, "chapter must be numeric")]
        source_chapters = [path for path in source_chapters if int(path.stem) == int(chapter)]
        if not source_chapters:
            return [_error(book.source_dir, f"source chapter {chapter} does not exist")]

    try:
        mode = book.annotation_mode()
    except ValueError as error:
        issues.append(_error(book.config_path, str(error)))
        mode = "dialogue"
    enabled_types = set(allowed_text_types(mode))
    names = _validate_persons(book, issues)

    for source in source_chapters:
        processed_path = book.processed_dir / source.name
        if not processed_path.exists():
            issues.append(_error(processed_path, "processed chapter is missing"))
            continue
        try:
            lines = read_processed(processed_path)
        except (OSError, ValueError) as error:
            issues.append(_error(processed_path, str(error)))
            continue
        actual_numbers = [line.number for line in lines]
        if actual_numbers != list(range(1, len(lines) + 1)):
            issues.append(
                _error(processed_path, "processed line numbers must be continuous from 1")
            )
        if any(not line.text.strip() for line in lines):
            issues.append(_error(processed_path, "processed text contains an empty line"))

        annotation_path = book.annotations_dir / f"{source.stem}.yaml"
        if not annotation_path.exists():
            issues.append(_warning(annotation_path, "annotation is missing"))
            continue
        try:
            annotation = load_annotation(annotation_path)
        except (OSError, ValueError) as error:
            issues.append(_error(annotation_path, str(error)))
            continue

        previous_end = 0
        for index, segment in enumerate(annotation.segments, 1):
            label = f"segment {index} ({segment.line.format()})"
            if segment.line.end > len(lines):
                issues.append(
                    _error(
                        annotation_path,
                        f"{label} exceeds chapter length {len(lines)}",
                    )
                )
            if segment.line.start <= previous_end:
                issues.append(_error(annotation_path, f"{label} overlaps or is out of order"))
            previous_end = max(previous_end, segment.line.end)
            if segment.name not in names:
                issues.append(
                    _error(
                        annotation_path,
                        f"{label} references unknown person {segment.name!r}",
                    )
                )
            if segment.type not in enabled_types:
                allowed = ", ".join(sorted(enabled_types))
                issues.append(
                    _error(
                        annotation_path,
                        f"{label} type {segment.type!r} is not allowed in {mode} mode; "
                        f"allowed values: {allowed}",
                    )
                )
            if segment.name == UNKNOWN_NAME and not segment.review:
                issues.append(_error(annotation_path, f"{label} uses UNKNOWN without review: true"))
            if segment.name != UNKNOWN_NAME and segment.review:
                issues.append(
                    _error(
                        annotation_path,
                        f"{label} uses review: true with resolved speaker {segment.name!r}",
                    )
                )
    return issues


def _validate_persons(book: Book, issues: list[ValidationIssue]) -> set[str]:
    path = book.persons_path
    if not path.exists():
        issues.append(_error(path, "persons.yaml is missing"))
        return set(SYSTEM_NAMES)
    try:
        people = load_persons(path)
    except (OSError, ValueError) as error:
        issues.append(_error(path, str(error)))
        return set(SYSTEM_NAMES)

    canonical_names = [person.name for person in people]
    for name, count in Counter(canonical_names).items():
        if count > 1:
            issues.append(_error(path, f"duplicate person name: {name}"))
        if name in SYSTEM_NAMES:
            issues.append(_error(path, f"reserved system name cannot be declared: {name}"))

    owner: dict[str, str] = {name: name for name in canonical_names}
    for person in people:
        local_aliases: set[str] = set()
        for alias in person.aliases:
            if alias in local_aliases:
                issues.append(_error(path, f"duplicate alias {alias!r} for {person.name}"))
            local_aliases.add(alias)
            if alias in SYSTEM_NAMES:
                issues.append(_error(path, f"reserved system name cannot be an alias: {alias}"))
            if alias in owner:
                if alias in canonical_names:
                    issues.append(_error(path, f"alias {alias!r} duplicates a canonical name"))
                elif owner[alias] != person.name:
                    issues.append(_error(path, f"alias {alias!r} conflicts with {owner[alias]}"))
            owner[alias] = person.name
    return set(canonical_names) | set(SYSTEM_NAMES)


def validate_scenes(book: Book) -> list[ValidationIssue]:
    """Validate optional scene metadata without consulting annotations."""
    path = book.scenes_path
    if not path.exists():
        return []
    issues: list[ValidationIssue] = []
    try:
        scenes = load_scenes(path)
    except (OSError, ValueError) as error:
        return [_error(path, str(error))]
    try:
        chapters = book.source_chapters()
    except ValueError as error:
        return [_error(book.source_dir, str(error))]

    chapter_by_number = {int(chapter.stem): chapter.stem for chapter in chapters}
    line_counts: dict[str, int] = {}
    for chapter in chapters:
        processed_path = book.processed_dir / chapter.name
        if not processed_path.exists():
            continue
        with suppress(OSError, ValueError):
            line_counts[chapter.stem] = len(read_processed(processed_path))

    for scene_id, count in Counter(scene.id for scene in scenes).items():
        if count > 1:
            issues.append(_error(path, f"duplicate scene id: {scene_id}"))

    occupied: dict[int, list[tuple[int, int, str]]] = {}
    for scene in scenes:
        for reference in scene.line:
            chapter_number = int(reference.chapter)
            stem = chapter_by_number.get(chapter_number)
            if stem is None:
                issues.append(
                    _error(path, f"{scene.id} references missing chapter {reference.chapter}")
                )
                continue
            line_count = line_counts.get(stem)
            if line_count is None:
                issues.append(_error(path, f"{scene.id} references unprocessed chapter {stem}"))
            elif reference.lines.end > line_count:
                issues.append(
                    _error(
                        path,
                        f"{scene.id} range {reference.format()} "
                        f"exceeds chapter length {line_count}",
                    )
                )
            occupied.setdefault(chapter_number, []).append(
                (reference.lines.start, reference.lines.end, scene.id)
            )

    for ranges in occupied.values():
        ranges.sort()
        previous: tuple[int, int, str] | None = None
        for current in ranges:
            if previous is not None and current[0] <= previous[1]:
                issues.append(
                    _error(
                        path,
                        f"scene ranges overlap: {previous[2]} and {current[2]}",
                    )
                )
            if previous is None or current[1] > previous[1]:
                previous = current
    return issues


def validate_book(book: Book, chapter: str | None = None) -> list[ValidationIssue]:
    issues = validate_annotations(book, chapter)
    if book.scenes_path.exists():
        issues.extend(validate_scenes(book))
    return issues


def _error(path: Path, message: str) -> ValidationIssue:
    return ValidationIssue("ERROR", path, message)


def _warning(path: Path, message: str) -> ValidationIssue:
    return ValidationIssue("WARNING", path, message)
