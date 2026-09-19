from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from . import annotation_schema as _annotation_schema

# Public domain constants; annotation_schema.yaml remains the vocabulary source of truth.
TextType = _annotation_schema.TextType
PersonRole = _annotation_schema.PersonRole
ReviewReason = _annotation_schema.ReviewReason
STYLE_FIELDS = _annotation_schema.STYLE_FIELDS
NARRATOR_NAME = _annotation_schema.NARRATOR_NAME
UNKNOWN_NAME = _annotation_schema.UNKNOWN_NAME
# Set-shaped views are convenient for membership checks in existing consumers.
REVIEW_REASONS = set(_annotation_schema.REVIEW_REASONS)
SYSTEM_NAMES = set(_annotation_schema.SYSTEM_NAMES)


@dataclass(frozen=True, order=True)
class LineRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start <= 0:
            raise ValueError("line number must be greater than zero")
        if self.end < self.start:
            raise ValueError("range end must not be less than range start")

    @classmethod
    def parse(cls, value: int | str) -> LineRange:
        if isinstance(value, bool):
            raise ValueError("boolean is not a line number")
        if isinstance(value, int):
            return cls(value, value)
        if not isinstance(value, str):
            raise ValueError("line must be an integer or a range string")
        value = value.strip()
        if "-" not in value:
            return cls(int(value), int(value))
        start, end = value.split("-", 1)
        return cls(int(start), int(end))

    def format(self) -> int | str:
        return self.start if self.start == self.end else f"{self.start}-{self.end}"

    def contains(self, other: LineRange) -> bool:
        return self.start <= other.start and self.end >= other.end


@dataclass(frozen=True)
class ChapterLineRange:
    chapter: str
    lines: LineRange

    @classmethod
    def parse(cls, value: str) -> ChapterLineRange:
        if not isinstance(value, str) or ":" not in value:
            raise ValueError("scene line must use chapter:line format")
        chapter, raw_lines = value.split(":", 1)
        chapter = chapter.strip()
        if not chapter.isdigit():
            raise ValueError(f"invalid chapter number: {chapter!r}")
        return cls(chapter, LineRange.parse(raw_lines))

    def format(self) -> str:
        return f"{self.chapter}:{self.lines.format()}"


@dataclass
class Person:
    name: str
    role: PersonRole
    aliases: list[str] = field(default_factory=list)


@dataclass
class Scene:
    id: str
    line: list[ChapterLineRange]
    summary: str

    def covers(self, chapter: str, lines: LineRange) -> bool:
        return any(
            int(ref.chapter) == int(chapter) and ref.lines.contains(lines) for ref in self.line
        )


@dataclass
class Segment:
    line: LineRange
    name: str
    type: TextType
    style: dict[str, str | None] | None
    scene_id: str
    review: bool = False
    review_reason: ReviewReason | None = None

    def merge_key(self) -> tuple[Any, ...]:
        style = (
            None
            if self.style is None
            else tuple((key, self.style.get(key)) for key in STYLE_FIELDS)
        )
        return (
            self.name,
            self.type,
            style,
            self.scene_id,
            self.review,
            self.review_reason,
        )


@dataclass
class Annotation:
    chapter: int | str
    segments: list[Segment]


@dataclass(frozen=True)
class ProcessedLine:
    number: int
    text: str


@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["ERROR", "WARNING"]
    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.severity} {self.path}: {self.message}"
