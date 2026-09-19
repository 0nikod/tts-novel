from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .annotation_schema import NARRATOR_NAME


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
        if not value:
            raise ValueError("line must not be empty")
        if "-" not in value:
            try:
                number = int(value)
            except ValueError as error:
                raise ValueError("line must be an integer or start-end range") from error
            return cls(number, number)
        parts = value.split("-")
        if len(parts) != 2:
            raise ValueError("line range must use start-end format")
        try:
            return cls(int(parts[0]), int(parts[1]))
        except ValueError as error:
            raise ValueError("line range must use integer start-end values") from error

    def format(self) -> int | str:
        return self.start if self.start == self.end else f"{self.start}-{self.end}"

    def contains(self, other: LineRange) -> bool:
        return self.start <= other.start and self.end >= other.end

    def overlaps(self, other: LineRange) -> bool:
        return self.start <= other.end and other.start <= self.end


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


@dataclass(frozen=True)
class Person:
    name: str
    aliases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Scene:
    id: str
    line: list[ChapterLineRange]
    summary: str

    def covers(self, chapter: str | int, lines: LineRange) -> bool:
        return any(
            int(reference.chapter) == int(chapter) and reference.lines.contains(lines)
            for reference in self.line
        )


@dataclass(frozen=True)
class Segment:
    line: LineRange
    name: str
    type: str = "dialogue"
    style: dict[str, str] | None = None
    review: bool = False

    def merge_key(self) -> tuple[Any, ...]:
        style = None if self.style is None else tuple(sorted(self.style.items()))
        return self.name, self.type, style, self.review

    @classmethod
    def narrator(cls, line: LineRange) -> Segment:
        return cls(line=line, name=NARRATOR_NAME, type="narration")


@dataclass(frozen=True)
class Annotation:
    segments: list[Segment] = field(default_factory=list)


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
