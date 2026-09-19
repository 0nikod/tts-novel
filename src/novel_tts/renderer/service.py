from __future__ import annotations

import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, Semaphore
from typing import Any, Protocol

from ..book import Book
from .audio import concatenate_wav, duration_ms, normalize_audio, transcode_final
from .cache import cache_path, copy_atomic, is_cache_hit
from .config import render_target
from .http import TTSRequestError
from .models import (
    AudioResult,
    CompiledStyle,
    RenderConfig,
    RenderIssue,
    RenderJob,
    RenderPlan,
    Voice,
)
from .planner import build_render_plan
from .providers import create_runner


class TTSBackend(Protocol):
    def synthesize(self, *, text: str, voice: Voice, style: CompiledStyle) -> AudioResult: ...


def run_render(
    book: Book,
    *,
    chapter: str | None = None,
    backend: TTSBackend | None = None,
) -> tuple[RenderPlan, dict[str, Any]]:
    plan, config = build_render_plan(book, chapter=chapter)
    if config is None or plan.errors:
        return plan, {}

    target = render_target(config)
    output_root = config.root / "output" / target
    manifest_path = config.root / "manifests" / f"{target}.json"
    output_root.mkdir(parents=True, exist_ok=True)
    (config.root / "cache").mkdir(parents=True, exist_ok=True)
    entries = [_manifest_entry(job, output_root) for job in plan.jobs]
    used_profiles = {job.profile.id: job.profile for job in plan.jobs}
    manifest: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "target": target,
        "default_profile": config.default_profile,
        "profiles": {
            profile_id: {
                "provider": profile.provider,
                "model": profile.model,
            }
            for profile_id, profile in sorted(used_profiles.items())
        },
        "chapter": chapter,
        "input_hashes": _input_hashes(book, config, plan),
        "jobs": entries,
        "completed": 0,
        "failed": 0,
        "assembled": False,
    }
    _write_json_atomic(manifest_path, manifest)

    runners = (
        {
            profile_id: create_runner(config.root, profile)
            for profile_id, profile in used_profiles.items()
        }
        if backend is None
        else {}
    )
    limits = {
        profile_id: Semaphore(profile.concurrency) for profile_id, profile in used_profiles.items()
    }
    locks = {job.cache_key: Lock() for job in plan.jobs}
    max_workers = max(1, sum(profile.concurrency for profile in used_profiles.values()))
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _render_job,
                    job,
                    segment_path(output_root, job),
                    config,
                    backend if backend is not None else runners[job.profile.id],
                    limits[job.profile.id],
                    locks[job.cache_key],
                ): index
                for index, job in enumerate(plan.jobs)
            }
            for future in as_completed(futures):
                index = futures[future]
                entries[index].update(future.result())
                _write_json_atomic(manifest_path, manifest)
    finally:
        for runner in runners.values():
            runner.close()

    manifest["completed"] = sum(entry["status"] == "completed" for entry in entries)
    manifest["failed"] = sum(entry["status"] == "failed" for entry in entries)
    if plan.jobs and not manifest["failed"]:
        completed = [(job, segment_path(output_root, job)) for job in plan.jobs]
        _assemble_outputs(completed, output_root, config, chapter_filter=chapter)
        manifest["assembled"] = True
    else:
        _remove_final_outputs(output_root, plan.jobs, chapter)
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    _write_json_atomic(manifest_path, manifest)
    return plan, manifest


def assemble_render(
    book: Book,
    *,
    chapter: str | None = None,
) -> tuple[RenderPlan, int]:
    plan, config = build_render_plan(book, chapter=chapter)
    if config is None or plan.errors:
        return plan, 0
    output_root = config.root / "output" / render_target(config)
    completed: list[tuple[RenderJob, Path]] = []
    missing: list[RenderJob] = []
    for job in plan.jobs:
        path = segment_path(output_root, job)
        if path.exists():
            completed.append((job, path))
        else:
            missing.append(job)
    if missing:
        plan.issues.append(RenderIssue("ERROR", f"{len(missing)} planned segment(s) are missing"))
        _remove_final_outputs(output_root, plan.jobs, chapter)
        return plan, len(completed)
    if completed:
        _assemble_outputs(completed, output_root, config, chapter_filter=chapter)
    return plan, len(completed)


def _render_job(
    job: RenderJob,
    destination: Path,
    config: RenderConfig,
    backend: TTSBackend,
    profile_limit: Semaphore,
    lock: Lock,
) -> dict[str, Any]:
    cached = cache_path(config.root, job.cache_key)
    entry: dict[str, Any] = {}
    try:
        with profile_limit, lock:
            if is_cache_hit(cached, config.output):
                entry["cache"] = "hit"
            else:
                cached.unlink(missing_ok=True)
                result = backend.synthesize(
                    text=job.text,
                    voice=job.voice,
                    style=job.compiled_style,
                )
                raw_path = cached.with_name(f"{cached.stem}.part.{result.audio_format}")
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(result.audio)
                try:
                    normalize_audio(
                        raw_path,
                        cached,
                        input_format=result.audio_format,
                        output=config.output,
                        input_sample_rate=result.input_sample_rate,
                    )
                finally:
                    raw_path.unlink(missing_ok=True)
                entry.update(
                    {
                        "cache": "miss",
                        "request_id": result.request_id,
                        "attempts": result.attempts,
                        "elapsed_ms": result.elapsed_ms,
                    }
                )
            copy_atomic(cached, destination)
        entry["duration_ms"] = duration_ms(destination)
        entry["status"] = "completed"
    except (OSError, ValueError, RuntimeError) as error:
        entry["status"] = "failed"
        entry["error"] = str(error)
        if isinstance(error, TTSRequestError):
            entry["attempts"] = error.attempts
            entry["elapsed_ms"] = error.elapsed_ms
    return entry


def segment_path(output_root: Path, job: RenderJob) -> Path:
    suffix = f"-c{job.chunk_index:03d}" if job.chunk_count > 1 else ""
    filename = f"{job.line_start:06d}-{job.line_end:06d}{suffix}.wav"
    return output_root / "segments" / job.chapter / filename


def _assemble_outputs(
    completed: list[tuple[RenderJob, Path]],
    output_root: Path,
    config: RenderConfig,
    *,
    chapter_filter: str | None,
) -> None:
    if chapter_filter is not None:
        stem = completed[0][0].chapter
        concatenate_wav(
            _with_gaps(completed, config),
            output_root / "chapters" / f"{stem}.wav",
            config.output,
        )
        return

    by_chapter: dict[str, list[tuple[RenderJob, Path]]] = {}
    for item in completed:
        by_chapter.setdefault(item[0].chapter, []).append(item)
    for stem, items in by_chapter.items():
        concatenate_wav(
            _with_gaps(items, config),
            output_root / "chapters" / f"{stem}.wav",
            config.output,
        )
    book_wav = output_root / "book.wav"
    concatenate_wav(_with_gaps(completed, config), book_wav, config.output)
    if config.output.final_format != "wav":
        transcode_final(book_wav, output_root / f"book.{config.output.final_format}")


def _with_gaps(items: list[tuple[RenderJob, Path]], config: RenderConfig) -> list[tuple[Path, int]]:
    result: list[tuple[Path, int]] = []
    for index, (job, path) in enumerate(items):
        if index == len(items) - 1:
            gap = 0
        else:
            next_job = items[index + 1][0]
            same_segment = (
                next_job.chapter == job.chapter
                and next_job.line_start == job.line_start
                and next_job.line_end == job.line_end
                and next_job.chunk_index == job.chunk_index + 1
            )
            if same_segment:
                gap = config.assembly.chunk_gap_ms
            elif next_job.chapter != job.chapter:
                gap = config.assembly.chapter_gap_ms
            elif next_job.scene_id != job.scene_id and (
                next_job.scene_id is not None or job.scene_id is not None
            ):
                gap = config.assembly.scene_gap_ms
            elif job.text_type == "dialogue":
                gap = config.assembly.dialogue_gap_ms
            else:
                gap = config.assembly.narration_gap_ms
        result.append((path, gap))
    return result


def _remove_final_outputs(
    output_root: Path, jobs: list[RenderJob], chapter_filter: str | None
) -> None:
    if chapter_filter is not None and jobs:
        (output_root / "chapters" / f"{jobs[0].chapter}.wav").unlink(missing_ok=True)
        return
    for path in output_root.glob("book.*"):
        path.unlink(missing_ok=True)
    shutil.rmtree(output_root / "chapters", ignore_errors=True)


def _manifest_entry(job: RenderJob, output_root: Path) -> dict[str, Any]:
    return {
        "id": job.id,
        "chapter": job.chapter,
        "line": job.line_start
        if job.line_start == job.line_end
        else f"{job.line_start}-{job.line_end}",
        "name": job.name,
        "type": job.text_type,
        "profile": job.profile.id,
        "provider": job.profile.provider,
        "model": job.profile.model,
        "voice": job.voice.id,
        "style": job.style,
        "cache_key": job.cache_key,
        "file": str(segment_path(output_root, job).relative_to(output_root)),
        "status": "pending",
    }


def _input_hashes(book: Book, config: RenderConfig, plan: RenderPlan) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, path in (
        ("config_sha256", config.root / "config.yaml"),
        ("voice_used_sha256", config.root / "voice_used.yaml"),
        ("voices_sha256", config.root / "voices.yaml"),
    ):
        if path.exists():
            result[label] = _sha256(path)
    chapters: dict[str, Any] = {}
    for stem in sorted({job.chapter for job in plan.jobs}, key=int):
        annotation = book.annotations_dir / f"{stem}.yaml"
        processed = book.processed_dir / f"{stem}.txt"
        chapters[stem] = {
            "annotation_sha256": _sha256(annotation),
            "processed_sha256": _sha256(processed),
        }
    result["chapters"] = chapters
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
