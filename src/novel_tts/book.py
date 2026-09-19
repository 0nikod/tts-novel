from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .annotation_schema import ANNOTATION_MODES, DEFAULT_ANNOTATION_MODE

_DEFAULT_RENDER_CONFIG = """endpoint: http://127.0.0.1:8000/v1/tts
model: custom-model
api_key_env: TTS_API_KEY
concurrency: 2
timeout_seconds: 120
retries: 2

output:
  sample_rate: 24000
  channels: 1
  final_format: mp3

assembly:
  dialogue_gap_ms: 180
  narration_gap_ms: 260
  scene_gap_ms: 800
  chapter_gap_ms: 1500

execution:
  max_chars_per_request: 200
"""


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
        return self.root / "persons.yaml"

    @property
    def scenes_path(self) -> Path:
        return self.root / "scenes.yaml"

    @property
    def config_path(self) -> Path:
        return self.root / "book.yaml"

    @property
    def render_dir(self) -> Path:
        return self.root / "render"

    @property
    def render_config_path(self) -> Path:
        return self.render_dir / "config.yaml"

    @property
    def voices_path(self) -> Path:
        return self.render_dir / "voices.yaml"

    @property
    def voice_used_path(self) -> Path:
        return self.render_dir / "voice_used.yaml"

    @property
    def styles_path(self) -> Path:
        return self.render_dir / "styles.yaml"

    def initialize(self) -> list[Path]:
        """Create a usable book skeleton without overwriting existing files."""
        created: list[Path] = []
        directories = (
            self.root,
            self.source_dir,
            self.processed_dir,
            self.annotations_dir,
            self.render_dir,
        )
        for directory in directories:
            if not directory.exists():
                directory.mkdir(parents=True)
                created.append(directory)
        defaults = {
            self.persons_path: "persons: []\n",
            self.render_config_path: _DEFAULT_RENDER_CONFIG,
            self.voices_path: "voices: {}\n",
            self.voice_used_path: "voices: {}\n",
            self.styles_path: "{}\n",
            self.render_dir / ".gitignore": "cache/\nmanifests/\noutput/\n",
        }
        for path, content in defaults.items():
            if not path.exists():
                path.write_text(content, encoding="utf-8")
                created.append(path)
        return created

    def chapter_paths(self, directory: Path, suffix: str = ".txt") -> list[Path]:
        paths = list(directory.glob(f"*{suffix}")) if directory.exists() else []
        invalid = [path.name for path in paths if not path.stem.isdigit()]
        if invalid:
            raise ValueError("chapter filenames must be numeric: " + ", ".join(sorted(invalid)))
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

    def annotation_chapters(self) -> list[Path]:
        return self.chapter_paths(self.annotations_dir, ".yaml")

    def resolve_chapter(self, chapter: str | int, directory: Path, suffix: str) -> Path:
        raw = str(chapter)
        if not raw.isdigit():
            raise ValueError("chapter must be numeric")
        matches = [
            path for path in self.chapter_paths(directory, suffix) if int(path.stem) == int(raw)
        ]
        if not matches:
            raise FileNotFoundError(f"chapter {raw} does not exist in {directory}")
        return matches[0]

    def resolve_source_chapter(self, chapter: str | int) -> Path:
        return self.resolve_chapter(chapter, self.source_dir, ".txt")

    def resolve_processed_chapter(self, chapter: str | int) -> Path:
        return self.resolve_chapter(chapter, self.processed_dir, ".txt")

    def chapter_stem(self, chapter: str | int) -> str:
        """Normalize a chapter identifier using the source filename."""
        return self.resolve_source_chapter(chapter).stem

    def annotation_path(self, chapter: str | int) -> Path:
        return self.annotations_dir / f"{self.chapter_stem(chapter)}.yaml"

    def annotation_mode(self) -> str:
        if not self.config_path.exists():
            return DEFAULT_ANNOTATION_MODE
        try:
            data: Any = yaml.safe_load(self.config_path.read_text(encoding="utf-8-sig"))
        except yaml.YAMLError as error:
            raise ValueError(f"invalid YAML in {self.config_path}: {error}") from error
        if data is None:
            return DEFAULT_ANNOTATION_MODE
        if not isinstance(data, dict):
            raise ValueError("book.yaml root must be a mapping")
        extra = set(data) - {"annotation"}
        if extra:
            raise ValueError("book.yaml has unsupported fields: " + ", ".join(sorted(extra)))
        annotation = data.get("annotation", {})
        if not isinstance(annotation, dict):
            raise ValueError("book.yaml annotation must be a mapping")
        extra = set(annotation) - {"mode"}
        if extra:
            raise ValueError(
                "book.yaml annotation has unsupported fields: " + ", ".join(sorted(extra))
            )
        mode = annotation.get("mode", DEFAULT_ANNOTATION_MODE)
        if mode not in ANNOTATION_MODES:
            allowed = ", ".join(ANNOTATION_MODES)
            raise ValueError(f"book.yaml annotation.mode must be one of: {allowed}; got {mode!r}")
        return mode
