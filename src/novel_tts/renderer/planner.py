from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from ..annotation_schema import SYSTEM_NAMES, UNKNOWN_NAME
from ..annotations import load_annotation
from ..book import Book
from ..persons import load_persons
from ..preprocessing import read_processed
from ..validation import validate_book
from .config import (
    load_render_config,
    load_voice_catalog,
    load_voice_usage,
    resolve_voice_source,
)
from .models import RenderConfig, RenderIssue, RenderJob, RenderPlan, RenderProfile, VoiceSpec
from .providers import get_driver
from .style import compile_style, load_style_mappings


def validate_render_configuration(
    book: Book, profile_id: str | None = None
) -> tuple[list[RenderIssue], RenderConfig | None]:
    issues: list[RenderIssue] = []
    try:
        config = load_render_config(book.root)
        load_style_mappings(config.root)
        known_names = {person.name for person in load_persons(book.persons_path)} | set(
            SYSTEM_NAMES
        )
        if profile_id is not None and profile_id not in config.profiles:
            raise ValueError(f"render profile {profile_id!r} does not exist")
        catalog = load_voice_catalog(config.root, config.profiles)
        usage = load_voice_usage(config.root, catalog, config.profiles)
        for name in catalog:
            if name not in known_names:
                issues.append(RenderIssue("ERROR", f"voice for unknown person {name!r}"))
        used_names: set[str] = set()
        for annotation_path in sorted(book.annotations_dir.glob("*.yaml")):
            used_names.update(segment.name for segment in load_annotation(annotation_path).segments)
        for name in sorted(used_names):
            try:
                resolve_voice_source(name, catalog, usage, forced_profile=profile_id)
            except ValueError as error:
                issues.append(RenderIssue("ERROR", str(error)))
    except ValueError as error:
        issues.append(RenderIssue("ERROR", str(error)))
        return issues, None
    return issues, config


def build_render_plan(
    book: Book,
    *,
    profile_id: str | None = None,
    chapter: str | None = None,
    scene_id: str | None = None,
    allow_review: bool = False,
) -> tuple[RenderPlan, RenderConfig | None]:
    plan = RenderPlan()
    structural = validate_book(book, chapter)
    for issue in structural:
        if issue.severity == "ERROR":
            plan.issues.append(RenderIssue("ERROR", f"{issue.path}: {issue.message}"))
    if plan.errors:
        return plan, None
    try:
        config = load_render_config(book.root)
        style_mappings = load_style_mappings(config.root)
    except ValueError as error:
        plan.issues.append(RenderIssue("ERROR", str(error)))
        return plan, None
    if profile_id is not None and profile_id not in config.profiles:
        plan.issues.append(RenderIssue("ERROR", f"render profile {profile_id!r} does not exist"))
        return plan, config

    try:
        catalog = load_voice_catalog(config.root, config.profiles)
        usage = load_voice_usage(config.root, catalog, config.profiles)
    except ValueError as error:
        plan.issues.append(RenderIssue("ERROR", str(error)))
        return plan, config

    for source_path in book.source_chapters():
        chapter_stem = source_path.stem
        if chapter is not None and int(chapter_stem) != int(chapter):
            continue
        annotation_path = book.annotations_dir / f"{chapter_stem}.yaml"
        processed_path = book.processed_dir / f"{chapter_stem}.txt"
        if not annotation_path.exists() or not processed_path.exists():
            continue
        annotation = load_annotation(annotation_path)
        text_by_line = {line.number: line.text for line in read_processed(processed_path)}
        for segment in annotation.segments:
            if scene_id is not None and segment.scene_id != scene_id:
                continue
            base_job_id = f"{chapter_stem}-{segment.line.start:06d}-{segment.line.end:06d}"
            try:
                selected_source = resolve_voice_source(
                    segment.name, catalog, usage, forced_profile=profile_id
                )
            except ValueError as error:
                plan.issues.append(RenderIssue("ERROR", str(error), base_job_id))
                continue
            profile = config.profiles[selected_source.profile_id]
            voice = selected_source.voice
            if segment.review and config.review.fail_on_review and not allow_review:
                plan.issues.append(
                    RenderIssue(
                        "ERROR",
                        f"segment requires review ({segment.review_reason or 'unspecified'})",
                        base_job_id,
                    )
                )
            if segment.name == UNKNOWN_NAME and config.review.fail_on_unknown:
                plan.issues.append(
                    RenderIssue("ERROR", f"{UNKNOWN_NAME} speaker cannot be rendered", base_job_id)
                )
            source_text = "\n".join(
                text_by_line[number] for number in range(segment.line.start, segment.line.end + 1)
            )
            chunks = split_text(source_text, config.execution.max_chars_per_request)
            for chunk_index, chunk_text in enumerate(chunks, 1):
                chunk_style = _style_for_chunk(segment.style, chunk_index, len(chunks))
                job_id = base_job_id if len(chunks) == 1 else f"{base_job_id}-c{chunk_index:03d}"
                compiled = compile_style(profile, chunk_text, chunk_style, style_mappings)
                if compiled.unsupported_fields:
                    message = "unsupported style values: " + ", ".join(compiled.unsupported_fields)
                    severity = "ERROR" if profile.unsupported_style == "error" else "WARNING"
                    plan.issues.append(RenderIssue(severity, message, job_id))
                cache_key = _cache_key(
                    config,
                    profile,
                    voice,
                    selected_source.id,
                    chunk_text,
                    chunk_style,
                    compiled.text,
                    compiled.instruction,
                )
                legacy_cache_key = (
                    _legacy_cache_key(
                        profile,
                        voice,
                        selected_source.id,
                        chunk_text,
                        chunk_style,
                        compiled.text,
                        compiled.instruction,
                    )
                    if len(chunks) == 1
                    else None
                )
                job = RenderJob(
                    id=job_id,
                    chapter=chapter_stem,
                    line_start=segment.line.start,
                    line_end=segment.line.end,
                    scene_id=segment.scene_id,
                    name=segment.name,
                    text_type=segment.type,
                    source_text=chunk_text,
                    style=chunk_style,
                    review=segment.review,
                    review_reason=segment.review_reason,
                    profile=profile,
                    voice=voice,
                    voice_source=selected_source.id,
                    chunk_index=chunk_index,
                    chunk_count=len(chunks),
                    compiled=compiled,
                    cache_key=cache_key,
                    legacy_cache_key=legacy_cache_key,
                )
                try:
                    get_driver(profile.provider).validate_profile(job)
                except ValueError as error:
                    plan.issues.append(RenderIssue("ERROR", str(error), job_id))
                plan.jobs.append(job)
    return plan, config


def _cache_key(
    config: RenderConfig,
    profile: RenderProfile,
    voice: VoiceSpec,
    voice_source: str,
    source_text: str,
    style: dict[str, str | None] | None,
    provider_text: str,
    instruction: str | None,
) -> str:
    voice_data = _voice_cache_data(voice)
    data = {
        "renderer_schema": 2,
        "normalizer_schema": 1,
        "output": asdict(config.output),
        "provider": profile.provider,
        "model": profile.model,
        "request": profile.request,
        "voice": voice_data,
        "voice_source": voice_source,
        "source_text": source_text,
        "provider_text": provider_text,
        "instruction": instruction,
        "style": style,
    }
    return _hash_cache_data(data)


def _legacy_cache_key(
    profile: RenderProfile,
    voice: VoiceSpec,
    voice_source: str,
    source_text: str,
    style: dict[str, str | None] | None,
    provider_text: str,
    instruction: str | None,
) -> str:
    data = {
        "renderer_schema": 1,
        "provider": profile.provider,
        "model": profile.model,
        "request": profile.request,
        "voice": _voice_cache_data(voice),
        "voice_source": voice_source,
        "source_text": source_text,
        "provider_text": provider_text,
        "instruction": instruction,
        "style": style,
    }
    return _hash_cache_data(data)


def _voice_cache_data(voice: VoiceSpec) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": voice.kind.value,
        "voice": voice.voice,
        "reference_id": voice.reference_id,
        "reference_text": voice.reference_text,
        "description": voice.description,
    }
    if voice.reference_audio is not None and voice.reference_audio.is_file():
        data["reference_audio_sha256"] = hashlib.sha256(
            voice.reference_audio.read_bytes()
        ).hexdigest()
    return data


def _hash_cache_data(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _style_for_chunk(
    style: dict[str, str | None] | None,
    chunk_index: int,
    chunk_count: int,
) -> dict[str, str | None] | None:
    if style is None or chunk_count == 1:
        return style
    chunk_style = dict(style)
    if chunk_index > 1:
        chunk_style["vocal_action_before"] = None
    if chunk_index < chunk_count:
        chunk_style["vocal_action_after"] = None
    return chunk_style


def split_text(text: str, max_chars: int) -> list[str]:
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
        minimum_boundary = start + max(1, max_chars // 2)
        cut = _last_boundary(text, start, hard_end, major_boundaries, minimum_boundary)
        if cut is None:
            cut = _last_boundary(text, start, hard_end, minor_boundaries, minimum_boundary)
        if cut is None:
            cut = hard_end
        while cut < len(text) and cut < hard_end and text[cut] in closing_marks:
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
    positions = [text.rfind(character, start, end) for character in boundaries]
    position = max(positions, default=-1)
    return position + 1 if position >= minimum else None
