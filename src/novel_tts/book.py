from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Book:
    root: Path

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    @property
    def processed_dir(self) -> Path:
        return self.root / "processed"

    @property
    def annotations_dir(self) -> Path:
        return self.root / "annotations"

    @property
    def persons_path(self) -> Path:
        return self.root / "persons.md"

    @property
    def scenes_path(self) -> Path:
        return self.root / "scenes.yaml"

    @property
    def voices_path(self) -> Path:
        return self.root / "voices.yaml"

    def initialize(self) -> list[Path]:
        created: list[Path] = []
        for directory in (self.root, self.source_dir, self.processed_dir, self.annotations_dir):
            if not directory.exists():
                directory.mkdir(parents=True)
                created.append(directory)
        defaults = {
            self.persons_path: "",
            self.scenes_path: "scenes: []\n",
            self.voices_path: "{}\n",
        }
        for path, content in defaults.items():
            if not path.exists():
                path.write_text(content, encoding="utf-8")
                created.append(path)
        return created

    def chapter_paths(self, directory: Path) -> list[Path]:
        paths = list(directory.glob("*.txt")) if directory.exists() else []
        invalid = [path.name for path in paths if not path.stem.isdigit()]
        if invalid:
            raise ValueError(
                "chapter filenames must be numeric: " + ", ".join(sorted(invalid))
            )
        by_number: dict[int, Path] = {}
        for path in paths:
            number = int(path.stem)
            if number in by_number:
                raise ValueError(
                    f"duplicate numeric chapter: {by_number[number].name} and {path.name}"
                )
            by_number[number] = path
        return [by_number[number] for number in sorted(by_number)]

    def source_chapters(self) -> list[Path]:
        return self.chapter_paths(self.source_dir)

    def processed_chapters(self) -> list[Path]:
        return self.chapter_paths(self.processed_dir)

    def chapter_order(self) -> dict[str, int]:
        return {path.stem: index for index, path in enumerate(self.source_chapters())}

    def resolve_source_chapter(self, chapter: str) -> Path:
        matches = [path for path in self.source_chapters() if int(path.stem) == int(chapter)]
        if not matches:
            raise FileNotFoundError(f"source chapter {chapter} does not exist")
        return matches[0]
