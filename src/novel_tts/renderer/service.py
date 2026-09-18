from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from threading import Lock, Semaphore
from typing import Any

import httpx

from ..book import Book
from .audio import (
    concatenate_wav,
    duration_ms,
    normalize_audio,
    transcode_final,
    validate_canonical_wave,
)
from .config import load_voice_catalog, load_voice_usage, render_target
from .http import TTSRequestError, send_request
from .models import RenderConfig, RenderIssue, RenderJob, RenderPlan
from .planner import build_render_plan
from .providers import get_driver
from .timeline import write_timeline


def run_render(
    book: Book,
    *,
    profile_id: str | None = None,
    chapter: str | None = None,
    scene_id: str | None = None,
    allow_review: bool = False,
    force: bool = False,
    allow_partial: bool = False,
) -> tuple[RenderPlan, dict[str, Any]]:
    plan, config = build_render_plan(
        book,
        profile_id=profile_id,
        chapter=chapter,
        scene_id=scene_id,
        allow_review=allow_review,
    )
    if config is None or plan.errors:
        return plan, {}
    assert isinstance(config, RenderConfig)
    catalog = load_voice_catalog(config.root, config.profiles)
    usage = load_voice_usage(config.root, catalog, config.profiles)
    target = render_target(profile_id, usage)
    output_root = config.root / "output" / target
    cache_root = config.root / "cache"
    manifest_path = config.root / "manifests" / f"{target}.json"
    output_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    snapshot_files = _snapshot_inputs(book, config, plan, output_root)
    entries: list[dict[str, Any]] = []
    segment_paths: list[Path] = []
    for job in plan.jobs:
        segment_path = output_root / _segment_relative_path(job)
        segment_paths.append(segment_path)
        entries.append(_manifest_entry(job, segment_path.relative_to(output_root)))
    manifest: dict[str, Any] = {
        "target": target,
        "selection": {
            "forced_profile": profile_id,
            "default_profile": usage.default_profile,
            "voices": usage.overrides,
        },
        "output": asdict(config.output),
        "snapshots": snapshot_files,
        "segments": entries,
    }
    _write_json_atomic(manifest_path, manifest)

    if force:
        for cache_key in {job.cache_key for job in plan.jobs}:
            (cache_root / f"{cache_key}.wav").unlink(missing_ok=True)
    profile_limits = {job.profile.id: Semaphore(job.profile.concurrency) for job in plan.jobs}
    cache_locks = {job.cache_key: Lock() for job in plan.jobs}
    completed_indexed: list[tuple[int, RenderJob, Path]] = []
    used_profiles = {job.profile.id for job in plan.jobs}
    max_workers = max(
        1, sum(config.profiles[profile_id].concurrency for profile_id in used_profiles)
    )
    clients = {
        profile_id: httpx.Client(timeout=config.profiles[profile_id].timeout_seconds)
        for profile_id in used_profiles
    }
    last_manifest_flush = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _render_job,
                    job,
                    segment_paths[index],
                    cache_root,
                    config,
                    profile_limits[job.profile.id],
                    cache_locks[job.cache_key],
                    clients[job.profile.id],
                    not force,
                ): index
                for index, job in enumerate(plan.jobs)
            }
            for completed_count, future in enumerate(as_completed(futures), 1):
                index = futures[future]
                entry, completed_path = future.result()
                entries[index].update(entry)
                if completed_path is not None:
                    completed_indexed.append((index, plan.jobs[index], completed_path))
                now = time.monotonic()
                if (
                    completed_count == len(futures)
                    or now - last_manifest_flush >= config.execution.manifest_flush_interval_seconds
                ):
                    _write_json_atomic(manifest_path, manifest)
                    last_manifest_flush = now
    finally:
        for client in clients.values():
            client.close()

    completed = [
        (job, path) for _index, job, path in sorted(completed_indexed, key=lambda item: item[0])
    ]
    manifest["completed"] = sum(item["status"] == "completed" for item in manifest["segments"])
    manifest["failed"] = sum(item["status"] == "failed" for item in manifest["segments"])
    complete_plan = len(completed) == len(plan.jobs)
    if completed and (complete_plan or allow_partial):
        _assemble_outputs(
            completed,
            output_root,
            config,
            chapter_filter=chapter,
            scene_filter=scene_id,
        )
        manifest["assembled"] = True
        manifest["partial"] = not complete_plan
    else:
        manifest["assembled"] = False
        manifest["partial"] = False
        if not complete_plan and plan.jobs:
            manifest["assembly_skipped_reason"] = (
                "not all planned segments completed; pass --allow-partial to opt in"
            )
            _clear_assembled_outputs(
                output_root,
                chapter_filter=(plan.jobs[0].chapter if chapter is not None else None),
                scene_filter=scene_id,
            )
    _write_json_atomic(manifest_path, manifest)
    return plan, manifest


def assemble_render(
    book: Book,
    *,
    profile_id: str | None = None,
    chapter: str | None = None,
    scene_id: str | None = None,
    allow_review: bool = False,
    allow_partial: bool = False,
) -> tuple[RenderPlan, int]:
    plan, config = build_render_plan(
        book,
        profile_id=profile_id,
        chapter=chapter,
        scene_id=scene_id,
        allow_review=allow_review,
    )
    if config is None or plan.errors:
        return plan, 0
    assert isinstance(config, RenderConfig)
    catalog = load_voice_catalog(config.root, config.profiles)
    usage = load_voice_usage(config.root, catalog, config.profiles)
    target = render_target(profile_id, usage)
    output_root = config.root / "output" / target
    completed: list[tuple[RenderJob, Path]] = []
    missing: list[RenderJob] = []
    for job in plan.jobs:
        path = output_root / _segment_relative_path(job)
        if path.exists():
            completed.append((job, path))
        else:
            missing.append(job)
    if missing and not allow_partial:
        plan.issues.append(
            RenderIssue(
                "ERROR",
                f"{len(missing)} planned segment(s) are missing; pass --allow-partial to opt in",
            )
        )
        _clear_assembled_outputs(
            output_root,
            chapter_filter=(plan.jobs[0].chapter if chapter is not None and plan.jobs else None),
            scene_filter=scene_id,
        )
        return plan, len(completed)
    if completed:
        _assemble_outputs(
            completed,
            output_root,
            config,
            chapter_filter=chapter,
            scene_filter=scene_id,
        )
    return plan, len(completed)


def _render_job(
    job: RenderJob,
    segment_path: Path,
    cache_root: Path,
    config: RenderConfig,
    profile_limit: Semaphore,
    cache_lock: Lock,
    client: httpx.Client,
    use_legacy_cache: bool,
) -> tuple[dict[str, Any], Path | None]:
    cache_path = cache_root / f"{job.cache_key}.wav"
    entry: dict[str, Any] = {}
    try:
        with profile_limit, cache_lock:
            if not cache_path.exists():
                migrated = False
                if use_legacy_cache and job.legacy_cache_key is not None:
                    legacy_path = cache_root / f"{job.legacy_cache_key}.wav"
                    if legacy_path.exists():
                        try:
                            validate_canonical_wave(legacy_path, config.output)
                        except (OSError, ValueError):
                            pass
                        else:
                            _copy_atomic(legacy_path, cache_path)
                            entry["cache"] = "migrated"
                            migrated = True
                if not migrated:
                    entry.update(_synthesize_job(job, cache_path, config, client))
                    entry["cache"] = "miss"
            else:
                # Reading duration also verifies that the cached WAV is structurally usable.
                try:
                    duration_ms(cache_path)
                    entry["cache"] = "hit"
                except (EOFError, OSError, ValueError):
                    cache_path.unlink(missing_ok=True)
                    entry.update(_synthesize_job(job, cache_path, config, client))
                    entry["cache"] = "miss"
            _copy_atomic(cache_path, segment_path)
        entry["duration_ms"] = duration_ms(segment_path)
        entry["status"] = "completed"
        return entry, segment_path
    except (OSError, ValueError) as error:
        entry["status"] = "failed"
        entry["error"] = str(error)
        if isinstance(error, TTSRequestError):
            entry["request_attempts"] = error.attempts
            entry["request_elapsed_ms"] = error.elapsed_ms
        return entry, None


def _synthesize_job(
    job: RenderJob,
    cache_path: Path,
    config: RenderConfig,
    client: httpx.Client,
) -> dict[str, Any]:
    api_key = os.environ.get(job.profile.api_key_env)
    if not api_key:
        raise ValueError(f"environment variable {job.profile.api_key_env} is not set")
    driver = get_driver(job.profile.provider)
    request = driver.prepare(job, api_key)
    response = send_request(
        request,
        timeout=job.profile.timeout_seconds,
        retries=job.profile.retries,
        client=client,
    )
    result = driver.decode(request, response.body)
    raw_path = cache_path.with_suffix(f".{result.audio_format}.part")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(result.audio)
    try:
        input_rate = _input_sample_rate(job, result.audio_format)
        normalize_audio(
            raw_path,
            cache_path,
            input_format=result.audio_format,
            output=config.output,
            input_sample_rate=input_rate,
        )
    finally:
        raw_path.unlink(missing_ok=True)
    return {
        "request_id": response.request_id,
        "request_attempts": response.attempts,
        "request_elapsed_ms": response.elapsed_ms,
    }


def _input_sample_rate(job: RenderJob, audio_format: str) -> int | None:
    if audio_format not in {"pcm", "pcm16"}:
        return None
    if job.profile.provider == "mimo":
        return 24000
    value = job.profile.request.get("sample_rate", 44100)
    return value if isinstance(value, int) else 44100


def _clear_assembled_outputs(
    output_root: Path,
    *,
    chapter_filter: str | None,
    scene_filter: str | None,
) -> None:
    if scene_filter is not None:
        (output_root / "scenes" / f"{scene_filter}.wav").unlink(missing_ok=True)
        for suffix in ("json", "srt", "vtt"):
            (output_root / "timelines" / "scenes" / f"{scene_filter}.{suffix}").unlink(
                missing_ok=True
            )
        return
    if chapter_filter is not None:
        (output_root / "chapters" / f"{chapter_filter}.wav").unlink(missing_ok=True)
        for suffix in ("json", "srt", "vtt"):
            (output_root / "timelines" / "chapters" / f"{chapter_filter}.{suffix}").unlink(
                missing_ok=True
            )
        return
    for path in output_root.glob("book.*"):
        path.unlink(missing_ok=True)
    for path in output_root.glob("subtitles.*"):
        path.unlink(missing_ok=True)
    (output_root / "timeline.json").unlink(missing_ok=True)
    for directory in ("scenes", "chapters", "timelines"):
        shutil.rmtree(output_root / directory, ignore_errors=True)


def _assemble_outputs(
    completed: list[tuple[RenderJob, Path]],
    output_root: Path,
    config: RenderConfig,
    *,
    chapter_filter: str | None,
    scene_filter: str | None,
) -> None:
    if scene_filter is not None:
        audio_path = output_root / "scenes" / f"{scene_filter}.wav"
        concatenate_wav(_with_internal_gaps(completed, config), audio_path, config.output)
        if config.timeline.enabled:
            write_timeline(
                _timeline_items(completed, config),
                audio_path=audio_path,
                destination=output_root / "timelines" / "scenes" / f"{scene_filter}.json",
                output_root=output_root,
                config=config,
                scope="scene",
            )
        return
    if chapter_filter is not None:
        chapter_name = completed[0][0].chapter
        audio_path = output_root / "chapters" / f"{chapter_name}.wav"
        concatenate_wav(_with_internal_gaps(completed, config), audio_path, config.output)
        if config.timeline.enabled:
            write_timeline(
                _timeline_items(completed, config),
                audio_path=audio_path,
                destination=output_root / "timelines" / "chapters" / f"{chapter_name}.json",
                output_root=output_root,
                config=config,
                scope="chapter",
            )
        return

    by_scene: dict[str, list[tuple[RenderJob, Path]]] = {}
    by_chapter: dict[str, list[tuple[RenderJob, Path]]] = {}
    for item in completed:
        by_scene.setdefault(item[0].scene_id, []).append(item)
        by_chapter.setdefault(item[0].chapter, []).append(item)

    book_wav = output_root / "book.wav"
    concatenate_wav(_with_internal_gaps(completed, config), book_wav, config.output)
    global_positions = None
    if config.timeline.enabled:
        global_positions = write_timeline(
            _timeline_items(completed, config),
            audio_path=book_wav,
            destination=output_root / "timeline.json",
            output_root=output_root,
            config=config,
            scope="book",
        )

    for scene, items in by_scene.items():
        audio_path = output_root / "scenes" / f"{scene}.wav"
        concatenate_wav(_with_internal_gaps(items, config), audio_path, config.output)
        if config.timeline.enabled:
            write_timeline(
                _timeline_items(items, config),
                audio_path=audio_path,
                destination=output_root / "timelines" / "scenes" / f"{scene}.json",
                output_root=output_root,
                config=config,
                scope="scene",
                global_positions=global_positions,
            )
    for chapter, items in by_chapter.items():
        audio_path = output_root / "chapters" / f"{chapter}.wav"
        concatenate_wav(_with_internal_gaps(items, config), audio_path, config.output)
        if config.timeline.enabled:
            write_timeline(
                _timeline_items(items, config),
                audio_path=audio_path,
                destination=output_root / "timelines" / "chapters" / f"{chapter}.json",
                output_root=output_root,
                config=config,
                scope="chapter",
                global_positions=global_positions,
            )
    if config.output.final_format != "wav":
        transcode_final(book_wav, output_root / f"book.{config.output.final_format}")


def _with_internal_gaps(
    items: list[tuple[RenderJob, Path]], config: RenderConfig
) -> list[tuple[Path, int]]:
    output: list[tuple[Path, int]] = []
    for index, (job, path) in enumerate(items):
        if index == len(items) - 1:
            gap = 0
        else:
            next_job = items[index + 1][0]
            if (
                next_job.chapter == job.chapter
                and next_job.line_start == job.line_start
                and next_job.line_end == job.line_end
                and next_job.chunk_index == job.chunk_index + 1
            ):
                gap = config.assembly.chunk_gap_ms
            elif next_job.chapter != job.chapter:
                gap = config.assembly.chapter_gap_ms
            elif next_job.scene_id != job.scene_id:
                gap = config.assembly.scene_gap_ms
            elif job.text_type == "dialogue":
                gap = config.assembly.dialogue_gap_ms
            else:
                gap = config.assembly.narration_gap_ms
        output.append((path, gap))
    return output


def _timeline_items(
    items: list[tuple[RenderJob, Path]], config: RenderConfig
) -> list[tuple[RenderJob, Path, int]]:
    gaps = _with_internal_gaps(items, config)
    return [
        (job, path, gap_ms) for (job, path), (_gap_path, gap_ms) in zip(items, gaps, strict=True)
    ]


def _manifest_entry(job: RenderJob, relative_path: Path) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "chapter": job.chapter,
        "line": (
            job.line_start if job.line_start == job.line_end else f"{job.line_start}-{job.line_end}"
        ),
        "scene_id": job.scene_id,
        "name": job.name,
        "type": job.text_type,
        "source_text": job.source_text,
        "provider_text": job.compiled.text,
        "instruction": job.compiled.instruction,
        "style": job.style,
        "profile": job.profile.id,
        "provider": job.profile.provider,
        "model": job.profile.model,
        "voice_kind": job.voice.kind.value,
        "voice_source": job.voice_source,
        "voice": _voice_manifest(job),
        "chunk_index": job.chunk_index,
        "chunk_count": job.chunk_count,
        "cache_key": job.cache_key,
        "file": str(relative_path),
        "status": "pending",
    }


def _segment_relative_path(job: RenderJob) -> Path:
    suffix = f"-c{job.chunk_index:03d}" if job.chunk_count > 1 else ""
    filename = f"{job.line_start:06d}-{job.line_end:06d}{suffix}.wav"
    return Path("segments") / job.chapter / filename


def _voice_manifest(job: RenderJob) -> dict[str, Any]:
    voice = job.voice
    data: dict[str, Any] = {
        "kind": voice.kind.value,
        "preset": voice.voice,
        "reference_id": voice.reference_id,
        "reference_text": voice.reference_text,
        "description": voice.description,
    }
    if voice.reference_audio is not None and voice.reference_audio.is_file():
        data["reference_audio_sha256"] = _sha256_file(voice.reference_audio)
    return {key: value for key, value in data.items() if value is not None}


def _snapshot_inputs(
    book: Book,
    config: RenderConfig,
    plan: RenderPlan,
    output_root: Path,
) -> list[dict[str, str]]:
    snapshot_root = output_root / "snapshots"
    shutil.rmtree(snapshot_root, ignore_errors=True)
    (output_root / "config.snapshot.yaml").unlink(missing_ok=True)
    chapters = sorted({job.chapter for job in plan.jobs}, key=int)
    paths = [
        config.root / "config.yaml",
        config.root / "voices.yaml",
        config.root / "voice_used.yaml",
        config.root / "styles.yaml",
        book.persons_path,
        book.scenes_path,
    ]
    for chapter in chapters:
        paths.extend(
            [
                book.source_dir / f"{chapter}.txt",
                book.processed_dir / f"{chapter}.txt",
                book.annotations_dir / f"{chapter}.yaml",
            ]
        )
    entries: list[dict[str, str]] = []
    for source in paths:
        if not source.is_file():
            continue
        relative = source.relative_to(book.root)
        destination = snapshot_root / relative
        _copy_atomic(source, destination)
        entries.append(
            {
                "source": str(relative),
                "snapshot": str(destination.relative_to(output_root)),
                "sha256": _sha256_file(source),
            }
        )
    _write_json_atomic(snapshot_root / "manifest.json", {"files": entries})
    return entries


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
