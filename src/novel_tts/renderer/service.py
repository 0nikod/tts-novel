from __future__ import annotations

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from threading import Lock, Semaphore
from typing import Any

from ..book import Book
from .audio import concatenate_wav, duration_ms, normalize_audio, transcode_final
from .http import send_request
from .models import RenderConfig, RenderJob, RenderPlan
from .planner import build_render_plan
from .providers import get_driver


def run_render(
    book: Book,
    *,
    profile_id: str | None = None,
    chapter: str | None = None,
    scene_id: str | None = None,
    allow_review: bool = False,
    force: bool = False,
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
    target = profile_id or (config.default_profile if not config.person_routes else "routed")
    output_root = config.root / "output" / target
    cache_root = config.root / "cache"
    manifest_path = config.root / "manifests" / f"{target}.json"
    output_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    _copy_atomic(config.root / "config.yaml", output_root / "config.snapshot.yaml")
    entries: list[dict[str, Any]] = []
    segment_paths: list[Path] = []
    for job in plan.jobs:
        segment_path = (
            output_root / "segments" / job.chapter / f"{job.line_start:06d}-{job.line_end:06d}.wav"
        )
        segment_paths.append(segment_path)
        entries.append(_manifest_entry(job, segment_path.relative_to(output_root)))
    manifest: dict[str, Any] = {
        "target": target,
        "output": asdict(config.output),
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
            ): index
            for index, job in enumerate(plan.jobs)
        }
        for future in as_completed(futures):
            index = futures[future]
            entry, completed_path = future.result()
            entries[index].update(entry)
            if completed_path is not None:
                completed_indexed.append((index, plan.jobs[index], completed_path))
            _write_json_atomic(manifest_path, manifest)

    completed = [
        (job, path) for _index, job, path in sorted(completed_indexed, key=lambda item: item[0])
    ]
    if completed:
        _assemble_outputs(
            completed,
            output_root,
            config,
            chapter_filter=chapter,
            scene_filter=scene_id,
        )
    manifest["completed"] = sum(item["status"] == "completed" for item in manifest["segments"])
    manifest["failed"] = sum(item["status"] == "failed" for item in manifest["segments"])
    _write_json_atomic(manifest_path, manifest)
    return plan, manifest


def assemble_render(
    book: Book,
    *,
    profile_id: str | None = None,
    chapter: str | None = None,
    scene_id: str | None = None,
    allow_review: bool = False,
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
    target = profile_id or (config.default_profile if not config.person_routes else "routed")
    output_root = config.root / "output" / target
    completed: list[tuple[RenderJob, Path]] = []
    for job in plan.jobs:
        path = (
            output_root / "segments" / job.chapter / f"{job.line_start:06d}-{job.line_end:06d}.wav"
        )
        if path.exists():
            completed.append((job, path))
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
) -> tuple[dict[str, Any], Path | None]:
    cache_path = cache_root / f"{job.cache_key}.wav"
    entry: dict[str, Any] = {}
    try:
        with profile_limit, cache_lock:
            if not cache_path.exists():
                _synthesize_job(job, cache_path, config)
                entry["cache"] = "miss"
            else:
                # Reading duration also verifies that the cached WAV is structurally usable.
                try:
                    duration_ms(cache_path)
                    entry["cache"] = "hit"
                except (EOFError, OSError, ValueError):
                    cache_path.unlink(missing_ok=True)
                    _synthesize_job(job, cache_path, config)
                    entry["cache"] = "miss"
            _copy_atomic(cache_path, segment_path)
        entry["duration_ms"] = duration_ms(segment_path)
        entry["status"] = "completed"
        return entry, segment_path
    except (OSError, ValueError) as error:
        entry["status"] = "failed"
        entry["error"] = str(error)
        return entry, None


def _synthesize_job(job: RenderJob, cache_path: Path, config: RenderConfig) -> None:
    api_key = os.environ.get(job.profile.api_key_env)
    if not api_key:
        raise ValueError(f"environment variable {job.profile.api_key_env} is not set")
    driver = get_driver(job.profile.provider)
    request = driver.prepare(job, api_key)
    body, _request_id = send_request(
        request,
        timeout=job.profile.timeout_seconds,
        retries=job.profile.retries,
    )
    result = driver.decode(request, body)
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


def _input_sample_rate(job: RenderJob, audio_format: str) -> int | None:
    if audio_format not in {"pcm", "pcm16"}:
        return None
    if job.profile.provider == "mimo":
        return 24000
    value = job.profile.request.get("sample_rate", 44100)
    return value if isinstance(value, int) else 44100


def _assemble_outputs(
    completed: list[tuple[RenderJob, Path]],
    output_root: Path,
    config: RenderConfig,
    *,
    chapter_filter: str | None,
    scene_filter: str | None,
) -> None:
    if scene_filter is not None:
        concatenate_wav(
            _with_internal_gaps(completed, config),
            output_root / "scenes" / f"{scene_filter}.wav",
            config.output,
        )
        return
    if chapter_filter is not None:
        chapter_name = completed[0][0].chapter
        concatenate_wav(
            _with_internal_gaps(completed, config),
            output_root / "chapters" / f"{chapter_name}.wav",
            config.output,
        )
        return

    by_scene: dict[str, list[tuple[RenderJob, Path]]] = {}
    by_chapter: dict[str, list[tuple[RenderJob, Path]]] = {}
    for item in completed:
        by_scene.setdefault(item[0].scene_id, []).append(item)
        by_chapter.setdefault(item[0].chapter, []).append(item)
    for scene, items in by_scene.items():
        concatenate_wav(
            _with_internal_gaps(items, config),
            output_root / "scenes" / f"{scene}.wav",
            config.output,
        )
    for chapter, items in by_chapter.items():
        concatenate_wav(
            _with_internal_gaps(items, config),
            output_root / "chapters" / f"{chapter}.wav",
            config.output,
        )
    book_wav = output_root / "book.wav"
    concatenate_wav(_with_internal_gaps(completed, config), book_wav, config.output)
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
            if next_job.chapter != job.chapter:
                gap = config.assembly.chapter_gap_ms
            elif next_job.scene_id != job.scene_id:
                gap = config.assembly.scene_gap_ms
            elif job.text_type == "dialogue":
                gap = config.assembly.dialogue_gap_ms
            else:
                gap = config.assembly.narration_gap_ms
        output.append((path, gap))
    return output


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
        "cache_key": job.cache_key,
        "file": str(relative_path),
        "status": "pending",
    }


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
