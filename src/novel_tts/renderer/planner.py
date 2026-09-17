from __future__ import annotations

import hashlib
import json
from typing import Any

from ..annotations import load_annotation
from ..book import Book
from ..persons import load_persons
from ..preprocessing import read_processed
from ..validation import validate_book
from .config import load_render_config, load_voice_file, validate_voice_for_profile
from .models import RenderConfig, RenderIssue, RenderJob, RenderPlan, RenderProfile, VoiceSpec
from .providers import get_driver
from .style import compile_style, load_style_mappings


def validate_render_configuration(book: Book) -> tuple[list[RenderIssue], RenderConfig | None]:
    issues: list[RenderIssue] = []
    try:
        config = load_render_config(book.root)
        load_style_mappings(config.root)
        known_names = {person.name for person in load_persons(book.persons_path)} | {
            "NARRATOR",
            "UNKNOWN",
        }
        for profile_id, profile in config.profiles.items():
            voices = load_voice_file(profile)
            for name, voice in voices.items():
                if name not in known_names:
                    issues.append(
                        RenderIssue(
                            "ERROR",
                            f"profile {profile_id} has voice for unknown person {name!r}",
                        )
                    )
                try:
                    validate_voice_for_profile(name, voice, profile)
                except ValueError as error:
                    issues.append(RenderIssue("ERROR", f"profile {profile_id}: {error}"))
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
) -> tuple[RenderPlan, Any]:
    plan = RenderPlan()
    structural = validate_book(book, chapter)
    for issue in structural:
        if issue.severity == "ERROR":
            plan.issues.append(RenderIssue("ERROR", f"{issue.path}: {issue.message}"))
    try:
        config = load_render_config(book.root)
        style_mappings = load_style_mappings(config.root)
    except ValueError as error:
        plan.issues.append(RenderIssue("ERROR", str(error)))
        return plan, None
    if profile_id is not None and profile_id not in config.profiles:
        plan.issues.append(RenderIssue("ERROR", f"render profile {profile_id!r} does not exist"))
        return plan, config

    voice_files: dict[str, dict[str, VoiceSpec]] = {}
    for current_id, profile in config.profiles.items():
        try:
            voice_files[current_id] = load_voice_file(profile)
        except ValueError as error:
            plan.issues.append(RenderIssue("ERROR", f"profile {current_id}: {error}"))
    if plan.errors:
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
            job_id = f"{chapter_stem}-{segment.line.start:06d}-{segment.line.end:06d}"
            selected_id = profile_id or config.person_routes.get(
                segment.name, config.default_profile
            )
            profile = config.profiles[selected_id]
            voice = voice_files[selected_id].get(segment.name)
            if segment.review and config.review.fail_on_review and not allow_review:
                plan.issues.append(
                    RenderIssue(
                        "ERROR",
                        f"segment requires review ({segment.review_reason or 'unspecified'})",
                        job_id,
                    )
                )
            if segment.name == "UNKNOWN" and config.review.fail_on_unknown:
                plan.issues.append(
                    RenderIssue("ERROR", "UNKNOWN speaker cannot be rendered", job_id)
                )
            if voice is None:
                plan.issues.append(
                    RenderIssue(
                        "ERROR",
                        f"profile {selected_id} has no voice for {segment.name!r}",
                        job_id,
                    )
                )
                continue
            try:
                validate_voice_for_profile(segment.name, voice, profile)
            except ValueError as error:
                plan.issues.append(RenderIssue("ERROR", str(error), job_id))
                continue
            source_text = "\n".join(
                text_by_line[number] for number in range(segment.line.start, segment.line.end + 1)
            )
            compiled = compile_style(profile, source_text, segment.style, style_mappings)
            if compiled.unsupported_fields:
                message = "unsupported style values: " + ", ".join(compiled.unsupported_fields)
                severity = "ERROR" if profile.unsupported_style == "error" else "WARNING"
                plan.issues.append(RenderIssue(severity, message, job_id))
            cache_key = _cache_key(
                profile,
                voice,
                source_text,
                segment.style,
                compiled.text,
                compiled.instruction,
            )
            job = RenderJob(
                id=job_id,
                chapter=chapter_stem,
                line_start=segment.line.start,
                line_end=segment.line.end,
                scene_id=segment.scene_id,
                name=segment.name,
                text_type=segment.type,
                source_text=source_text,
                style=segment.style,
                review=segment.review,
                review_reason=segment.review_reason,
                profile=profile,
                voice=voice,
                compiled=compiled,
                cache_key=cache_key,
            )
            try:
                get_driver(profile.provider).validate_profile(job)
            except ValueError as error:
                plan.issues.append(RenderIssue("ERROR", str(error), job_id))
            plan.jobs.append(job)
    return plan, config


def _cache_key(
    profile: RenderProfile,
    voice: VoiceSpec,
    source_text: str,
    style: dict[str, str | None] | None,
    provider_text: str,
    instruction: str | None,
) -> str:
    voice_data: dict[str, Any] = {
        "kind": voice.kind.value,
        "voice": voice.voice,
        "reference_id": voice.reference_id,
        "reference_text": voice.reference_text,
        "description": voice.description,
    }
    if voice.reference_audio is not None and voice.reference_audio.is_file():
        voice_data["reference_audio_sha256"] = hashlib.sha256(
            voice.reference_audio.read_bytes()
        ).hexdigest()
    data = {
        "renderer_schema": 1,
        "provider": profile.provider,
        "model": profile.model,
        "request": profile.request,
        "voice": voice_data,
        "source_text": source_text,
        "provider_text": provider_text,
        "instruction": instruction,
        "style": style,
    }
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
