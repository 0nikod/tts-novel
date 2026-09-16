from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

import yaml

from .annotations import load_annotation
from .book import Book
from .models import REVIEW_REASONS, STYLE_FIELDS, SYSTEM_NAMES, ValidationIssue
from .persons import load_persons
from .preprocessing import read_processed
from .scenes import SCENE_ID_RE, load_scenes

VALID_TYPES = {"narration", "dialogue", "thought"}


class Validator:
    def __init__(self, book: Book):
        self.book = book
        self.issues: list[ValidationIssue] = []

    def error(self, path: Path, message: str) -> None:
        self.issues.append(ValidationIssue("ERROR", path, message))

    def warning(self, path: Path, message: str) -> None:
        self.issues.append(ValidationIssue("WARNING", path, message))

    def validate(self, chapter: str | None = None) -> list[ValidationIssue]:
        self.issues = []
        try:
            source_paths = self.book.source_chapters()
        except ValueError as error:
            self.error(self.book.source_dir, str(error))
            return self.issues

        source_by_stem = {path.stem: path for path in source_paths}
        source_by_number = {int(stem): stem for stem in source_by_stem}
        if chapter is not None:
            if not chapter.isdigit():
                self.error(self.book.source_dir, "chapter must be numeric")
                return self.issues
            if int(chapter) not in source_by_number:
                self.error(self.book.source_dir, f"source chapter {chapter} does not exist")
                return self.issues
        processed_counts = self._validate_processed(source_by_stem, chapter)
        people_names = self._validate_persons()
        self._validate_voices(people_names)
        scenes, scene_indexes = self._validate_scenes(
            source_by_stem, source_by_number, processed_counts
        )
        self._validate_annotations(
            source_by_stem,
            source_by_number,
            processed_counts,
            people_names,
            scenes,
            scene_indexes,
            chapter,
        )
        return self.issues

    def _validate_processed(
        self, source_by_stem: dict[str, Path], chapter: str | None
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        selected = {
            stem: path
            for stem, path in source_by_stem.items()
            if chapter is None or int(stem) == int(chapter)
        }
        for stem, source_path in selected.items():
            path = self.book.processed_dir / source_path.name
            if not path.exists():
                self.error(path, "processed chapter is missing")
                continue
            try:
                lines = read_processed(path)
            except ValueError as error:
                self.error(path, str(error))
                continue
            expected = list(range(1, len(lines) + 1))
            actual = [line.number for line in lines]
            if actual != expected:
                self.error(path, "processed line numbers must be continuous from 1")
            if any(not line.text.strip() for line in lines):
                self.error(path, "processed text contains an empty line")
            counts[stem] = len(lines)

        # Scene validation needs counts from unselected chapters too.
        if chapter is not None:
            for stem, source_path in source_by_stem.items():
                if stem in counts or int(stem) == int(chapter):
                    continue
                path = self.book.processed_dir / source_path.name
                if path.exists():
                    with suppress(ValueError):
                        counts[stem] = len(read_processed(path))
        return counts

    def _validate_persons(self) -> set[str]:
        path = self.book.persons_path
        if not path.exists():
            self.error(path, "persons.md is missing")
            return set(SYSTEM_NAMES)
        try:
            people = load_persons(path)
        except ValueError as error:
            self.error(path, str(error))
            return set(SYSTEM_NAMES)
        names = [person.name for person in people]
        for name, count in Counter(names).items():
            if count > 1:
                self.error(path, f"duplicate person name: {name}")
            if name in SYSTEM_NAMES:
                self.error(path, f"reserved system name cannot be declared: {name}")
        owner: dict[str, str] = {name: name for name in names}
        for person in people:
            seen_local: set[str] = set()
            for alias in person.aliases:
                if alias in seen_local:
                    self.error(path, f"duplicate alias {alias!r} for {person.name}")
                seen_local.add(alias)
                if alias in SYSTEM_NAMES:
                    self.error(path, f"reserved system name cannot be an alias: {alias}")
                if alias in owner:
                    if alias in names:
                        self.error(path, f"alias {alias!r} duplicates a canonical name")
                    elif owner[alias] != person.name:
                        self.error(path, f"alias {alias!r} conflicts with {owner[alias]}")
                owner[alias] = person.name
        return set(names) | SYSTEM_NAMES

    def _validate_voices(self, people_names: set[str]) -> None:
        path = self.book.voices_path
        if not path.exists():
            self.warning(path, "voices.yaml is missing")
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        except yaml.YAMLError as error:
            self.error(path, f"invalid YAML: {error}")
            return
        if data is None:
            data = {}
        if not isinstance(data, dict):
            self.error(path, "voices root must be a mapping")
            return
        for name, config in data.items():
            if not isinstance(name, str):
                self.error(path, "voice names must be strings")
                continue
            if name not in people_names:
                self.error(path, f"voice references unknown person {name!r}")
            if not isinstance(config, dict):
                self.error(path, f"voice {name!r} must be a mapping")
                continue
            forbidden = set(config) & {"speaker_id", "speaker-id", "speaker_token", "speaker-token"}
            if forbidden:
                self.error(
                    path,
                    f"voice {name!r} persists renderer-only fields: "
                    + ", ".join(sorted(forbidden)),
                )
            reference_id = config.get("reference_id")
            if not isinstance(reference_id, str) or not reference_id.strip():
                self.error(path, f"voice {name!r} requires a non-empty reference_id")

    def _validate_scenes(
        self,
        source_by_stem: dict[str, Path],
        source_by_number: dict[int, str],
        processed_counts: dict[str, int],
    ) -> tuple[dict[str, object], dict[str, int]]:
        path = self.book.scenes_path
        if not path.exists():
            self.error(path, "scenes.yaml is missing")
            return {}, {}
        try:
            scene_list = load_scenes(path)
        except ValueError as error:
            self.error(path, str(error))
            return {}, {}
        ids = [scene.id for scene in scene_list]
        for scene_id, count in Counter(ids).items():
            if count > 1:
                self.error(path, f"duplicate scene id: {scene_id}")
        numbers: list[int] = []
        for scene in scene_list:
            match = SCENE_ID_RE.match(scene.id)
            if not match:
                self.error(path, f"invalid scene id: {scene.id}")
            else:
                numbers.append(int(match.group(1)))
            if not scene.summary.strip():
                self.error(path, f"{scene.id} has an empty summary")
            if not scene.line:
                self.error(path, f"{scene.id} has no line range")
        if numbers and numbers != list(range(1, len(numbers) + 1)):
            self.error(path, "scene ids must be continuous and ordered from S0001")

        chapter_rank = {stem: index for index, stem in enumerate(source_by_stem)}
        previous_end: tuple[int, int] | None = None
        for scene in scene_list:
            local_previous: tuple[int, int] | None = None
            for ref in scene.line:
                try:
                    stem = source_by_number[int(ref.chapter)]
                except KeyError:
                    self.error(path, f"{scene.id} references missing chapter {ref.chapter}")
                    continue
                count = processed_counts.get(stem)
                if count is None:
                    self.error(path, f"{scene.id} references unprocessed chapter {stem}")
                elif ref.lines.end > count:
                    self.error(
                        path,
                        f"{scene.id} range {ref.format()} exceeds chapter length {count}",
                    )
                start = (chapter_rank[stem], ref.lines.start)
                end = (chapter_rank[stem], ref.lines.end)
                if local_previous is not None and start <= local_previous:
                    self.error(path, f"{scene.id} line ranges are not ordered")
                if previous_end is not None and start <= previous_end:
                    self.error(path, f"scene ranges overlap or are out of order at {ref.format()}")
                local_previous = end
                previous_end = end
        return (
            {scene.id: scene for scene in scene_list},
            {scene.id: index for index, scene in enumerate(scene_list)},
        )

    def _validate_annotations(
        self,
        source_by_stem: dict[str, Path],
        source_by_number: dict[int, str],
        processed_counts: dict[str, int],
        people_names: set[str],
        scenes: dict[str, object],
        scene_indexes: dict[str, int],
        chapter: str | None,
    ) -> None:
        for stem in source_by_stem:
            if chapter is not None and int(stem) != int(chapter):
                continue
            if stem not in processed_counts:
                continue
            path = self.book.annotations_dir / f"{stem}.yaml"
            if not path.exists():
                self.warning(path, "annotation is missing")
                continue
            try:
                annotation = load_annotation(path)
            except ValueError as error:
                self.error(path, str(error))
                continue
            if int(annotation.chapter) != int(stem):
                self.error(path, f"chapter field does not match filename {stem}")

            line_count = processed_counts[stem]
            covered = [0] * (line_count + 1)
            previous_end = 0
            previous_scene_index = -1
            previous_segment = None
            for index, segment in enumerate(annotation.segments, 1):
                label = f"segment {index} ({segment.line.format()})"
                if segment.line.end > line_count:
                    self.error(path, f"{label} exceeds chapter length {line_count}")
                if segment.line.start <= previous_end:
                    self.error(path, f"{label} overlaps or is out of order")
                if (
                    previous_segment is not None
                    and previous_segment.line.end + 1 == segment.line.start
                    and previous_segment.merge_key() == segment.merge_key()
                ):
                    self.warning(path, f"{label} can be merged with the preceding segment")
                previous_segment = segment
                previous_end = max(previous_end, segment.line.end)
                for number in range(segment.line.start, min(segment.line.end, line_count) + 1):
                    covered[number] += 1
                if segment.name not in people_names:
                    self.error(path, f"{label} references unknown person {segment.name!r}")
                if segment.type not in VALID_TYPES:
                    self.error(path, f"{label} has invalid type {segment.type!r}")
                self._validate_style(path, label, segment.style)
                if segment.review:
                    if segment.review_reason not in REVIEW_REASONS:
                        self.error(path, f"{label} requires a valid review_reason")
                elif segment.review_reason is not None:
                    self.error(path, f"{label} has review_reason without review: true")
                if segment.name == "UNKNOWN" and not segment.review:
                    self.warning(path, f"{label} uses UNKNOWN without review: true")

                scene = scenes.get(segment.scene_id)
                if scene is None:
                    self.error(path, f"{label} references missing scene {segment.scene_id}")
                else:
                    # Scene is a Scene; object keeps this module independent of casts.
                    if not scene.covers(stem, segment.line):  # type: ignore[attr-defined]
                        self.error(path, f"{label} is outside scene {segment.scene_id}")
                    current_scene_index = scene_indexes[segment.scene_id]
                    if current_scene_index < previous_scene_index:
                        self.error(path, f"{label} moves backwards in scene order")
                    previous_scene_index = current_scene_index

            missing = [number for number in range(1, line_count + 1) if covered[number] == 0]
            overlaps = [number for number in range(1, line_count + 1) if covered[number] > 1]
            if missing:
                self.error(path, f"uncovered lines: {self._compact_numbers(missing)}")
            if overlaps:
                self.error(path, f"multiply covered lines: {self._compact_numbers(overlaps)}")

    def _validate_style(self, path: Path, label: str, style: dict[str, str | None] | None) -> None:
        if style is None:
            return
        unknown = set(style) - set(STYLE_FIELDS)
        if unknown:
            self.error(path, f"{label} has unknown style fields: {', '.join(sorted(unknown))}")
        if not style:
            self.warning(path, f"{label} should use style: null instead of an empty mapping")
        for key, value in style.items():
            if value is not None and not isinstance(value, str):
                self.error(path, f"{label} style.{key} must be a string or null")

    @staticmethod
    def _compact_numbers(numbers: Iterable[int]) -> str:
        values = list(numbers)
        if not values:
            return ""
        ranges: list[str] = []
        start = previous = values[0]
        for number in values[1:]:
            if number == previous + 1:
                previous = number
                continue
            ranges.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = number
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        return ", ".join(ranges)


def validate_book(book: Book, chapter: str | None = None) -> list[ValidationIssue]:
    return Validator(book).validate(chapter)
