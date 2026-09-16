from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import ProcessedLine


OPEN_TO_CLOSE = {
    "“": "”",
    "‘": "’",
    "„": "“",
    "「": "」",
    "『": "』",
    "﹁": "﹂",
    "﹃": "﹄",
    "〝": "〞",
    "«": "»",
    "‹": "›",
    '"': '"',
    "＂": "＂",
}
CLOSERS = set(OPEN_TO_CLOSE.values())
PROCESSED_RE = re.compile(r"^(\d+)-(.*)$")


@dataclass(frozen=True)
class PreprocessResult:
    lines: list[str]
    warnings: list[str]


def split_direct_speech(paragraph: str) -> tuple[list[str], list[str]]:
    """Split top-level quoted spans from surrounding text without changing characters."""
    pieces: list[str] = []
    warnings: list[str] = []
    stack: list[str] = []
    piece_start = 0
    quote_start: int | None = None

    for index, char in enumerate(paragraph):
        if stack and char == stack[-1]:
            stack.pop()
            if not stack and quote_start is not None:
                quoted = paragraph[quote_start : index + 1].strip()
                if quoted:
                    pieces.append(quoted)
                piece_start = index + 1
                quote_start = None
            continue

        if char in OPEN_TO_CLOSE:
            # A symmetric quote closes when it is already at the top.
            if stack and OPEN_TO_CLOSE[char] == char and stack[-1] == char:
                continue
            if not stack:
                prefix = paragraph[piece_start:index].strip()
                if prefix:
                    pieces.append(prefix)
                quote_start = index
            stack.append(OPEN_TO_CLOSE[char])
        elif char in CLOSERS and not stack:
            warnings.append(f"unmatched closing quote {char!r} at character {index + 1}")

    if stack:
        warnings.append("unclosed quote: expected " + " ".join(reversed(stack)))
        # Keep the incomplete quotation intact rather than dropping it.
        tail_start = quote_start if quote_start is not None else piece_start
        tail = paragraph[tail_start:].strip()
        if tail:
            pieces.append(tail)
    else:
        suffix = paragraph[piece_start:].strip()
        if suffix:
            pieces.append(suffix)

    return pieces, warnings


def preprocess_text(text: str) -> PreprocessResult:
    output: list[str] = []
    warnings: list[str] = []
    # Novel TXT files conventionally use one physical line per paragraph.
    for source_number, raw in enumerate(text.splitlines(), start=1):
        paragraph = raw.strip()
        if not paragraph:
            continue
        pieces, paragraph_warnings = split_direct_speech(paragraph)
        output.extend(pieces)
        warnings.extend(
            f"source line {source_number}: {warning}" for warning in paragraph_warnings
        )
    return PreprocessResult(output, warnings)


def format_processed(lines: list[str]) -> str:
    if not lines:
        return ""
    return "".join(f"{number}-{text}\n" for number, text in enumerate(lines, start=1))


def preprocess_file(source: Path, destination: Path) -> PreprocessResult:
    result = preprocess_text(source.read_text(encoding="utf-8-sig"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(format_processed(result.lines), encoding="utf-8")
    return result


def read_processed(path: Path) -> list[ProcessedLine]:
    lines: list[ProcessedLine] = []
    for physical_number, raw in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        match = PROCESSED_RE.match(raw)
        if not match:
            raise ValueError(f"physical line {physical_number} has invalid format")
        lines.append(ProcessedLine(int(match.group(1)), match.group(2)))
    return lines
