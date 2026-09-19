from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from ..annotation_schema import SYSTEM_NAMES, UNKNOWN_NAME
from ..annotations import load_annotation, materialize_annotation
from ..book import Book
from ..persons import load_persons
from ..preprocessing import read_processed
from ..scenes import load_scenes, split_range_at_scenes
from ..validation import validate_book
from .config import load_render_config, load_voice_catalog, load_voice_usage, resolve_voice
from .models import CompiledStyle, RenderConfig, RenderIssue, RenderJob, RenderPlan, Voice
from .style import compile_style, load_style_mappings


def validate_render_configuration(book: Book) -> tuple[list[RenderIssue], RenderConfig | None]:
    """Validate custom backend configuration and the effective casting."""
    plan, config = build_render_plan(book)
    return plan.issues, config


def build_render_plan(
    book: Book,
    *,
    chapter: str | None = None,
) -> tuple[RenderPlan, RenderConfig | None]:
    plan = RenderPlan()
    for issue in validate_book(book, chapter):
        if issue.severity == "ERROR":
            plan.issues.append(RenderIssue("ERROR", f"{issue.path}: {issue.message}"))

    try:
        config = load_render_config(book.root)
        catalog = load_voice_catalog(config.root)
        usage = load_voice_usage(config.root, catalog)
        style_mappings = load_style_mappings(config.root)
        people = load_persons(book.persons_path)
        scenes = load_scenes(book.scenes_path)
    except (OSError, ValueError) as error:
        plan.issues.append(RenderIssue("ERROR", str(error)))
        return plan, None

    known_names = {person.name for person in people} | set(SYSTEM_NAMES)
    for name in sorted(set(usage) - known_names):
        plan.issues.append(RenderIssue("ERROR", f"voice selected for unknown person {name!r}"))

    try:
        source_chapters = book.source_chapters()
    except ValueError as error:
        plan.issues.append(RenderIssue("ERROR", str(error)))
        return plan, config
    if chapter is not None:
        if not chapter.isdigit():
            plan.issues.append(RenderIssue("ERROR", "chapter must be numeric"))
            return plan, config
        source_chapters = [path for path in source_chapters if int(path.stem) == int(chapter)]
        if not source_chapters:
            plan.issues.append(RenderIssue("ERROR", f"source chapter {chapter} does not exist"))
            return plan, config

    chapter_data: list[tuple[str, list[Any], list[Any]]] = []
    used_names: set[str] = set()
    for source_path in source_chapters:
        stem = source_path.stem
        processed_path = book.processed_dir / source_path.name
        annotation_path = book.annotations_dir / f"{stem}.yaml"
        if not processed_path.exists():
            continue
        if not annotation_path.exists():
            plan.issues.append(RenderIssue("ERROR", f"annotation is missing: {annotation_path}"))
            continue
        try:
            processed = read_processed(processed_path)
            sparse = load_annotation(annotation_path)
            effective = materialize_annotation(processed, sparse.segments)
        except (OSError, ValueError) as error:
            plan.issues.append(RenderIssue("ERROR", f"{stem}: {error}"))
            continue
        chapter_data.append((stem, processed, effective))
        used_names.update(segment.name for segment in effective)

    if UNKNOWN_NAME in used_names:
        plan.issues.append(RenderIssue("ERROR", "UNKNOWN speaker cannot be rendered"))
    missing_voices = sorted(
        name for name in used_names if name != UNKNOWN_NAME and name not in usage
    )
    if missing_voices:
        plan.issues.append(
            RenderIssue("ERROR", "Missing voices:\n  " + "\n  ".join(missing_voices))
        )
    if plan.errors:
        return plan, config

    for stem, processed, effective in chapter_data:
        text_by_line = {line.number: line.text for line in processed}
        for segment in effective:
            for lines, scene_id in split_range_at_scenes(scenes, stem, segment.line):
                segment_text = "\n".join(
                    text_by_line[number] for number in range(lines.start, lines.end + 1)
                )
                chunks = split_text(segment_text, config.execution.max_chars_per_request)
                voice = resolve_voice(segment.name, catalog, usage)
                for chunk_index, text in enumerate(chunks, 1):
                    chunk_style = style_for_chunk(segment.style, chunk_index, len(chunks))
                    compiled = compile_style(chunk_style, style_mappings)
                    base_id = f"{stem}-{lines.start:06d}-{lines.end:06d}"
                    job_id = base_id if len(chunks) == 1 else f"{base_id}-c{chunk_index:03d}"
                    cache_key = make_cache_key(
                        config=config,
                        text=text,
                        voice=voice,
                        style=compiled,
                    )
                    plan.jobs.append(
                        RenderJob(
                            id=job_id,
                            chapter=stem,
                            line_start=lines.start,
                            line_end=lines.end,
                            text=text,
                            name=segment.name,
                            text_type=segment.type,
                            style=chunk_style,
                            voice=voice,
                            chunk_index=chunk_index,
                            chunk_count=len(chunks),
                            cache_key=cache_key,
                            compiled_style=compiled,
                            scene_id=scene_id,
                        )
                    )
    return plan, config


def make_cache_key(
    *,
    config: RenderConfig,
    text: str,
    voice: Voice,
    style: CompiledStyle,
) -> str:
    data: dict[str, Any] = {
        "cache_schema": 1,
        "endpoint": config.endpoint,
        "model": config.model,
        "text": text,
        "voice": {"id": voice.id, "parameters": voice.parameters},
        "style": style.values,
        "output": asdict(config.output),
    }
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def style_for_chunk(
    style: dict[str, str] | None,
    chunk_index: int,
    chunk_count: int,
) -> dict[str, str] | None:
    if style is None or chunk_count == 1:
        return style
    result = dict(style)
    if chunk_index > 1:
        result.pop("vocal_action_before", None)
    if chunk_index < chunk_count:
        result.pop("vocal_action_after", None)
    return result or None


def split_text(text: str, max_chars: int) -> list[str]:
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    major_boundaries = "\n。！？!?；;"
    minor_boundaries = "，,、：:"
    closing_marks = "”’」』）》】"
    while start < len(text):
        hard_end = min(start + max_chars, len(text))
        if hard_end == len(text):
            chunks.append(text[start:])
            break
        minimum = start + max(1, max_chars // 2)
        cut = _last_boundary(text, start, hard_end, major_boundaries, minimum)
        if cut is None:
            cut = _last_boundary(text, start, hard_end, minor_boundaries, minimum)
        if cut is None:
            cut = hard_end
        while cut < hard_end and text[cut] in closing_marks:
            cut += 1
        chunks.append(text[start:cut])
        start = cut
    if "".join(chunks) != text or any(not chunk for chunk in chunks):
        raise ValueError("internal error while splitting renderer text")
    return chunks


def _last_boundary(
    text: str,
    start: int,
    end: int,
    boundaries: str,
    minimum: int,
) -> int | None:
    position = max((text.rfind(character, start, end) for character in boundaries), default=-1)
    return position + 1 if position >= minimum else None
