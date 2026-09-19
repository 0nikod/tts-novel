from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import typer
from dotenv import load_dotenv

from .annotations import complete_annotation, load_annotation, save_annotation
from .book import Book
from .models import Annotation
from .preprocessing import preprocess_file, read_processed
from .renderer.audio import validate_canonical_wave
from .renderer.capabilities import all_capabilities
from .renderer.config import (
    load_render_config,
    load_voice_catalog,
    load_voice_usage,
    render_target,
)
from .renderer.planner import build_render_plan, validate_render_configuration
from .renderer.service import assemble_render, run_render
from .scenes import find_scene, load_scenes
from .validation import validate_book

app = typer.Typer(
    no_args_is_help=True,
    help="Prepare, validate, and render novel text for TTS.",
)
render_app = typer.Typer(no_args_is_help=True, help="Plan and run TTS rendering.")
app.add_typer(render_app, name="render")


def get_book(path: Path) -> Book:
    return Book(path.expanduser().resolve())


@app.command()
def init(
    book_path: Path = typer.Argument(..., help="Book directory to create"),
) -> None:
    """Create the standard directory structure without overwriting files."""
    book = get_book(book_path)
    created = book.initialize()
    if not created:
        typer.echo(f"Already initialized: {book.root}")
        return
    typer.echo(f"Initialized: {book.root}")
    for path in created:
        typer.echo(f"  created {path.relative_to(book.root) if path != book.root else '.'}")


@app.command()
def status(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Show chapter processing, annotation, and review counts."""
    book = get_book(book_path)
    try:
        chapters = book.source_chapters()
    except ValueError as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(1) from error
    processed = 0
    annotated = 0
    reviews = 0
    typer.echo(f"Book: {book.root}")
    for source in chapters:
        processed_path = book.processed_dir / source.name
        annotation_path = book.annotations_dir / f"{source.stem}.yaml"
        state: list[str] = []
        if processed_path.exists():
            processed += 1
            state.append("processed")
        if annotation_path.exists():
            annotated += 1
            state.append("annotated")
            try:
                annotation = load_annotation(annotation_path)
                count = sum(segment.review for segment in annotation.segments)
                reviews += count
                if count:
                    state.append(f"review={count}")
            except ValueError:
                state.append("invalid-annotation")
        typer.echo(f"  {source.stem}: {', '.join(state) if state else 'source only'}")
    typer.echo(
        f"Total: {len(chapters)} chapters, {processed} processed, "
        f"{annotated} annotated, {reviews} review items"
    )


@app.command()
def preprocess(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str | None = typer.Option(None, "--chapter", "-c", help="Numeric chapter"),
) -> None:
    """Split direct speech and number processed lines."""
    book = get_book(book_path)
    try:
        sources = (
            [book.resolve_source_chapter(chapter)]
            if chapter is not None
            else book.source_chapters()
        )
    except (ValueError, FileNotFoundError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(1) from error
    if not sources:
        typer.echo("No source chapters found.")
        return
    for source in sources:
        destination = book.processed_dir / source.name
        result = preprocess_file(source, destination)
        typer.echo(f"{source.name}: wrote {len(result.lines)} lines to {destination}")
        for warning in result.warnings:
            typer.echo(f"  WARNING: {warning}", err=True)


@app.command("validate")
def validate_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str | None = typer.Option(None, "--chapter", "-c", help="Numeric chapter"),
    output_format: str = typer.Option("text", "--format", help="Output format: text or json"),
) -> None:
    """Validate processed text, people, scenes, and annotations."""
    if chapter is not None and not chapter.isdigit():
        typer.echo("ERROR: chapter must be numeric", err=True)
        raise typer.Exit(2)
    if output_format not in {"text", "json"}:
        typer.echo("ERROR: format must be text or json", err=True)
        raise typer.Exit(2)
    issues = validate_book(get_book(book_path), chapter)
    errors = sum(issue.severity == "ERROR" for issue in issues)
    warnings = sum(issue.severity == "WARNING" for issue in issues)
    if output_format == "json":
        typer.echo(
            json.dumps(
                {
                    "errors": errors,
                    "warnings": warnings,
                    "issues": [
                        {
                            "severity": issue.severity,
                            "path": str(issue.path),
                            "message": issue.message,
                        }
                        for issue in issues
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for issue in issues:
            typer.echo(str(issue), err=issue.severity == "ERROR")
        typer.echo(f"Validation complete: {errors} error(s), {warnings} warning(s)")
    if errors:
        raise typer.Exit(1)


@app.command()
def review(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """List all segments that require human review, including their text."""
    book = get_book(book_path)
    total = 0
    try:
        chapters = book.source_chapters()
        scenes = load_scenes(book.scenes_path)
    except (ValueError, OSError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(1) from error
    for source in chapters:
        annotation_path = book.annotations_dir / f"{source.stem}.yaml"
        processed_path = book.processed_dir / source.name
        if not annotation_path.exists() or not processed_path.exists():
            continue
        try:
            annotation = load_annotation(annotation_path)
            text_by_line = {line.number: line.text for line in read_processed(processed_path)}
        except ValueError as error:
            typer.echo(f"ERROR {annotation_path}: {error}", err=True)
            continue
        for segment in annotation.segments:
            scene = find_scene(scenes, source.stem, segment.line)
            scene_label = scene.id if scene is not None else "<unmapped>"
            if not segment.review:
                continue
            total += 1
            typer.echo(
                f"[{source.stem}:{segment.line.format()}] "
                f"{segment.review_reason or 'unspecified'} | "
                f"{segment.name}/{segment.type} | {scene_label}"
            )
            for number in range(segment.line.start, segment.line.end + 1):
                typer.echo(f"  {number}-{text_by_line.get(number, '<missing>')}")
    typer.echo(f"Total review items: {total}")


@app.command("fill-annotations")
def fill_annotations(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str | None = typer.Option(None, "--chapter", "-c", help="Numeric chapter"),
) -> None:
    """Fill uncovered processed lines with NARRATOR narration segments."""
    if chapter is not None and not chapter.isdigit():
        typer.echo("ERROR: chapter must be numeric", err=True)
        raise typer.Exit(2)

    book = get_book(book_path)
    try:
        chapters = book.source_chapters()
        scenes = load_scenes(book.scenes_path)
    except (ValueError, OSError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(1) from error

    selected = [
        source for source in chapters if chapter is None or int(source.stem) == int(chapter)
    ]
    if not selected:
        typer.echo("ERROR: no matching source chapters", err=True)
        raise typer.Exit(1)

    inputs: list[tuple[Path, Annotation, int]] = []
    input_errors: list[str] = []
    for source in selected:
        annotation_path = book.annotations_dir / f"{source.stem}.yaml"
        processed_path = book.processed_dir / source.name
        if not annotation_path.exists():
            input_errors.append(f"{annotation_path}: annotation is missing")
            continue
        if not processed_path.exists():
            input_errors.append(f"{processed_path}: processed chapter is missing")
            continue
        try:
            annotation = load_annotation(annotation_path)
            line_count = len(read_processed(processed_path))
        except (OSError, ValueError) as error:
            input_errors.append(f"{annotation_path}: {error}")
            continue
        inputs.append((annotation_path, annotation, line_count))

    if input_errors:
        for message in input_errors:
            typer.echo(f"ERROR {message}", err=True)
        raise typer.Exit(1)

    issues = validate_book(book, chapter, require_coverage=False)
    errors = [issue for issue in issues if issue.severity == "ERROR"]
    for issue in issues:
        if issue.severity == "WARNING":
            typer.echo(str(issue), err=True)
    if errors:
        for issue in errors:
            typer.echo(str(issue), err=True)
        raise typer.Exit(1)

    completed: list[tuple[Path, Annotation]] = []
    added_segments = 0
    completion_errors: list[str] = []
    for annotation_path, annotation, line_count in inputs:
        try:
            result = complete_annotation(annotation, line_count, scenes)
        except ValueError as error:
            completion_errors.append(f"{annotation_path}: {error}")
            continue
        completed.append((annotation_path, result))
        added_segments += len(result.segments) - len(annotation.segments)

    if completion_errors:
        for message in completion_errors:
            typer.echo(f"ERROR {message}", err=True)
        raise typer.Exit(1)

    temporary_paths: list[tuple[Path, Path]] = []
    try:
        for destination, annotation in completed:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            save_annotation(temporary, annotation)
            temporary_paths.append((temporary, destination))
        for temporary, destination in temporary_paths:
            os.replace(temporary, destination)
    except OSError as error:
        typer.echo(f"ERROR: could not write completed annotations: {error}", err=True)
        raise typer.Exit(1) from error
    finally:
        for temporary, _destination in temporary_paths:
            temporary.unlink(missing_ok=True)

    typer.echo(
        f"Completed {len(completed)} chapter(s); added {added_segments} narrator segment(s)."
    )


@render_app.command("capabilities")
def render_capabilities() -> None:
    """List model capabilities known to this renderer version."""
    for capability in all_capabilities():
        typer.echo(f"{capability.provider}/{capability.model}")
        typer.echo("  voices: " + ", ".join(sorted(mode.value for mode in capability.voice_modes)))
        typer.echo(
            "  streaming: " + ", ".join(sorted(mode.value for mode in capability.streaming_modes))
        )
        typer.echo("  formats: " + ", ".join(sorted(capability.output_formats)))
        typer.echo("  style: " + ", ".join(sorted(capability.style_controls)))


@render_app.command("validate-config")
def render_validate_config(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Validate renderer configuration, voices, styles, and model capabilities."""
    issues, config = validate_render_configuration(get_book(book_path), profile_id=profile)
    _print_render_issues(issues)
    if any(str(issue).startswith("ERROR") for issue in issues):
        raise typer.Exit(1)
    profile_count = len(config.profiles) if config is not None else 0
    typer.echo(f"Render configuration is valid; {profile_count} profile(s) checked.")


@render_app.command("plan")
def render_plan_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    chapter: str | None = typer.Option(None, "--chapter", "-c"),
    scene: str | None = typer.Option(None, "--scene"),
    allow_review: bool = typer.Option(False, "--allow-review"),
) -> None:
    """Build a dry-run plan without calling a paid API."""
    plan, config = build_render_plan(
        get_book(book_path),
        profile_id=profile,
        chapter=chapter,
        scene_id=scene,
        allow_review=allow_review,
    )
    _print_render_issues(plan.issues)
    characters = sum(len(job.source_text) for job in plan.jobs)
    profiles = sorted({job.profile.id for job in plan.jobs})
    cache_hits = 0
    cache_migrations = 0
    if config is not None:
        for job in plan.jobs:
            if (config.root / "cache" / f"{job.cache_key}.wav").exists():
                cache_hits += 1
            elif job.legacy_cache_key is not None:
                legacy_path = config.root / "cache" / f"{job.legacy_cache_key}.wav"
                try:
                    validate_canonical_wave(legacy_path, config.output)
                except (FileNotFoundError, OSError, ValueError):
                    continue
                cache_migrations += 1
    cache_misses = len(plan.jobs) - cache_hits - cache_migrations
    typer.echo(
        f"Plan: {len(plan.jobs)} job(s), {characters} character(s), "
        f"cache={cache_hits} hit/{cache_migrations} migratable/{cache_misses} miss, "
        f"profiles={','.join(profiles) or '-'}"
    )
    if plan.errors:
        raise typer.Exit(1)


@render_app.command("run")
def render_run_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    chapter: str | None = typer.Option(None, "--chapter", "-c"),
    scene: str | None = typer.Option(None, "--scene"),
    allow_review: bool = typer.Option(False, "--allow-review"),
    force: bool = typer.Option(False, "--force"),
    allow_partial: bool = typer.Option(False, "--allow-partial"),
    env_file: Path | None = typer.Option(None, "--env-file"),
) -> None:
    """Synthesize segments, use the cache, and assemble complete audio."""
    if env_file is not None:
        if not env_file.is_file():
            typer.echo(f"ERROR: env file does not exist: {env_file}", err=True)
            raise typer.Exit(1)
        load_dotenv(env_file, override=False)
    plan, manifest = run_render(
        get_book(book_path),
        profile_id=profile,
        chapter=chapter,
        scene_id=scene,
        allow_review=allow_review,
        force=force,
        allow_partial=allow_partial,
    )
    _print_render_issues(plan.issues)
    if plan.errors:
        raise typer.Exit(1)
    completed = manifest.get("completed", 0)
    failed = manifest.get("failed", 0)
    typer.echo(f"Render complete: {completed} completed, {failed} failed")
    if failed:
        raise typer.Exit(1)


@render_app.command("assemble")
def render_assemble_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    chapter: str | None = typer.Option(None, "--chapter", "-c"),
    scene: str | None = typer.Option(None, "--scene"),
    allow_review: bool = typer.Option(False, "--allow-review"),
    allow_partial: bool = typer.Option(False, "--allow-partial"),
) -> None:
    """Reassemble existing segment WAV files without making API calls."""
    plan, count = assemble_render(
        get_book(book_path),
        profile_id=profile,
        chapter=chapter,
        scene_id=scene,
        allow_review=allow_review,
        allow_partial=allow_partial,
    )
    _print_render_issues(plan.issues)
    if plan.errors:
        raise typer.Exit(1)
    typer.echo(f"Assembled {count} existing segment(s).")


@render_app.command("status")
def render_status_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show status from a render manifest."""
    book = get_book(book_path)
    try:
        config = load_render_config(book.root)
        catalog = load_voice_catalog(config.root, config.profiles)
        usage = load_voice_usage(config.root, catalog, config.profiles)
    except ValueError as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(1) from error
    if profile is not None and profile not in config.profiles:
        typer.echo(f"ERROR: render profile {profile!r} does not exist", err=True)
        raise typer.Exit(1)
    target = render_target(profile, usage)
    path = config.root / "manifests" / f"{target}.json"
    if not path.exists():
        typer.echo(f"No manifest found for {target}.")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if "assembled" not in data:
        assembly = "assembly status unknown (legacy manifest)"
    else:
        assembly = "assembled" if data["assembled"] else "not assembled"
    if data.get("partial"):
        assembly = "partially assembled"
    typer.echo(
        f"{target}: {data.get('completed', 0)} completed, "
        f"{data.get('failed', 0)} failed, {assembly}"
    )


def _print_render_issues(issues: list[object]) -> None:
    for issue in issues:
        typer.echo(str(issue), err=str(issue).startswith("ERROR"))


if __name__ == "__main__":
    app()
