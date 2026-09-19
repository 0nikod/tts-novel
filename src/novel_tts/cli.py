from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv

from .annotations import load_annotation, materialize_annotation, segment_to_dict
from .book import Book
from .context import build_agent_context, format_agent_context
from .persons import load_persons
from .preprocessing import preprocess_file, read_processed
from .renderer.cache import cache_path, is_cache_hit
from .renderer.config import load_voice_catalog, load_voice_usage
from .renderer.planner import build_render_plan, validate_render_configuration
from .renderer.service import assemble_render, run_render
from .schema_codegen import render_annotation_schema, write_annotation_schema
from .validation import validate_book

app = typer.Typer(no_args_is_help=True, help="Prepare, annotate, and render novels for TTS.")
render_app = typer.Typer(no_args_is_help=True, help="Plan and run private custom TTS rendering.")
schema_app = typer.Typer(no_args_is_help=True, help="Generate machine-readable schemas.")
app.add_typer(render_app, name="render")
app.add_typer(schema_app, name="schema")


def get_book(path: Path) -> Book:
    return Book(path.expanduser().resolve())


@app.command()
def init(book_path: Path = typer.Argument(..., help="Book directory to create")) -> None:
    """Create a book skeleton without overwriting files."""
    book = get_book(book_path)
    created = book.initialize()
    if not created:
        typer.echo(f"Already initialized: {book.root}")
        return
    typer.echo(f"Initialized: {book.root}")
    for path in created:
        relative = "." if path == book.root else path.relative_to(book.root)
        typer.echo(f"  created {relative}")


@app.command()
def preprocess(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str | None = typer.Option(None, "--chapter", "-c", help="Numeric chapter"),
) -> None:
    """Apply the stable quote splitter and write numbered processed text."""
    book = get_book(book_path)
    try:
        sources = [book.resolve_source_chapter(chapter)] if chapter else book.source_chapters()
    except (FileNotFoundError, ValueError) as error:
        _fail(str(error))
    if not sources:
        typer.echo("No source chapters found.")
        return
    for source in sources:
        destination = book.processed_dir / source.name
        result = preprocess_file(source, destination)
        typer.echo(f"{source.name}: wrote {len(result.lines)} lines")
        for warning in result.warnings:
            typer.echo(f"WARNING {warning}", err=True)


@app.command("agent-context")
def agent_context_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str = typer.Argument(..., help="Numeric chapter"),
    previous_lines: int = typer.Option(20, "--previous-lines", min=0),
    no_existing: bool = typer.Option(False, "--no-existing"),
    output_format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    """Print the minimal context needed to annotate one chapter."""
    if output_format not in {"text", "json"}:
        _fail("format must be text or json", 2)
    try:
        context = build_agent_context(
            get_book(book_path),
            chapter,
            previous_lines=previous_lines,
            include_existing=not no_existing,
        )
    except (OSError, ValueError) as error:
        _fail(str(error))
    if output_format == "json":
        typer.echo(json.dumps(context, ensure_ascii=False, indent=2))
    else:
        typer.echo(format_agent_context(context), nl=False)


@app.command("validate")
def validate_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str | None = typer.Option(None, "--chapter", "-c"),
    output_format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    """Validate sparse annotations and optional scene metadata."""
    if output_format not in {"text", "json"}:
        _fail("format must be text or json", 2)
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
def inspect(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str = typer.Option(..., "--chapter", "-c"),
    output_format: str = typer.Option("text", "--format", help="text, yaml, or json"),
) -> None:
    """Show runtime effective annotations without changing sparse YAML."""
    if output_format not in {"text", "yaml", "json"}:
        _fail("format must be text, yaml, or json", 2)
    book = get_book(book_path)
    try:
        processed_path = book.resolve_processed_chapter(chapter)
        annotation_path = book.annotations_dir / f"{processed_path.stem}.yaml"
        if not annotation_path.exists():
            raise ValueError(f"annotation does not exist: {annotation_path}")
        effective = materialize_annotation(
            read_processed(processed_path), load_annotation(annotation_path).segments
        )
    except (OSError, ValueError) as error:
        _fail(str(error))
    if output_format == "text":
        for segment in effective:
            review = "    review" if segment.review else ""
            typer.echo(
                f"{processed_path.stem}:{str(segment.line.format()):<9} "
                f"{segment.name:<14} {segment.type}{review}"
            )
        return
    data = {"segments": [_effective_segment_data(segment) for segment in effective]}
    if output_format == "json":
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        typer.echo(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), nl=False)


@app.command()
def review(book_path: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Show only sparse segments marked review: true."""
    book = get_book(book_path)
    total = 0
    try:
        annotations = book.annotation_chapters()
    except ValueError as error:
        _fail(str(error))
    for path in annotations:
        processed_path = book.processed_dir / f"{path.stem}.txt"
        if not processed_path.exists():
            continue
        try:
            annotation = load_annotation(path)
            text = {line.number: line.text for line in read_processed(processed_path)}
        except (OSError, ValueError) as error:
            typer.echo(f"ERROR {path}: {error}", err=True)
            continue
        for segment in annotation.segments:
            if not segment.review:
                continue
            total += 1
            typer.echo(f"[{path.stem}:{segment.line.format()}]")
            typer.echo(f"speaker: {segment.name}")
            typer.echo(f"type: {segment.type}")
            for number in range(segment.line.start, segment.line.end + 1):
                typer.echo(f"{number}-{text.get(number, '<missing>')}")
            typer.echo()
    typer.echo(f"Total review items: {total}")


@app.command()
def status(book_path: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Show concise annotation and casting progress."""
    book = get_book(book_path)
    try:
        chapters = book.source_chapters()
    except ValueError as error:
        _fail(str(error))
    review_count = 0
    effective_names: set[str] = set()
    typer.echo(f"Book: {book.root.name}")
    typer.echo()
    for source in chapters:
        processed_path = book.processed_dir / source.name
        annotation_path = book.annotations_dir / f"{source.stem}.yaml"
        states: list[str] = []
        if processed_path.exists():
            states.append("processed")
        if annotation_path.exists():
            states.append("annotated")
            try:
                annotation = load_annotation(annotation_path)
                count = sum(segment.review for segment in annotation.segments)
                review_count += count
                if count:
                    states.append(f"review={count}")
                if processed_path.exists():
                    effective_names.update(
                        segment.name
                        for segment in materialize_annotation(
                            read_processed(processed_path), annotation.segments
                        )
                    )
            except (OSError, ValueError):
                states.append("invalid-annotation")
        typer.echo(f"{source.stem}: {', '.join(states) if states else 'source-only'}")

    try:
        person_count = len(load_persons(book.persons_path))
    except (OSError, ValueError):
        person_count = 0
    typer.echo()
    typer.echo(f"Persons: {person_count}")
    typer.echo(f"Review items: {review_count}")
    typer.echo(f"Scenes: {'available' if book.scenes_path.exists() else 'not available'}")
    try:
        catalog = load_voice_catalog(book.render_dir)
        usage = load_voice_usage(book.render_dir, catalog)
        configured = len(effective_names & set(usage))
        typer.echo(f"Casting: {configured}/{len(effective_names)} speakers configured")
    except (OSError, ValueError):
        typer.echo(f"Casting: unavailable (0/{len(effective_names)})")


@schema_app.command("annotation")
def schema_annotation(
    output: Path | None = typer.Option(None, "--output", "-o"),
) -> None:
    """Print or write the generated sparse annotation JSON Schema YAML."""
    if output is None:
        typer.echo(render_annotation_schema(), nl=False)
    else:
        write_annotation_schema(output)
        typer.echo(output)


@render_app.command("validate")
def render_validate(book_path: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Validate custom backend configuration and all effective casting."""
    issues, config = validate_render_configuration(get_book(book_path))
    _print_render_issues(issues)
    if any(issue.severity == "ERROR" for issue in issues):
        raise typer.Exit(1)
    typer.echo(f"Render configuration is valid for model {config.model if config else '-'}.")


@render_app.command("plan")
def render_plan_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str | None = typer.Option(None, "--chapter", "-c"),
) -> None:
    """Build a dry-run render plan without calling the custom API."""
    plan, config = build_render_plan(get_book(book_path), chapter=chapter)
    _print_render_issues(plan.issues)
    hits = 0
    if config is not None:
        hits = sum(
            is_cache_hit(cache_path(config.root, job.cache_key), config.output) for job in plan.jobs
        )
    characters = sum(len(job.text) for job in plan.jobs)
    typer.echo(
        f"Plan: {len(plan.jobs)} job(s), {characters} character(s), "
        f"cache={hits} hit/{len(plan.jobs) - hits} miss"
    )
    if plan.errors:
        raise typer.Exit(1)


@render_app.command("run")
def render_run_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str | None = typer.Option(None, "--chapter", "-c"),
    env_file: Path | None = typer.Option(None, "--env-file"),
) -> None:
    """Synthesize missing cache entries and assemble only after complete success."""
    if env_file is not None:
        if not env_file.is_file():
            _fail(f"env file does not exist: {env_file}")
        load_dotenv(env_file, override=False)
    plan, manifest = run_render(get_book(book_path), chapter=chapter)
    _print_render_issues(plan.issues)
    if plan.errors:
        raise typer.Exit(1)
    typer.echo(
        f"Render complete: {manifest.get('completed', 0)} completed, "
        f"{manifest.get('failed', 0)} failed, "
        f"assembled={'yes' if manifest.get('assembled') else 'no'}"
    )
    if manifest.get("failed"):
        raise typer.Exit(1)


@render_app.command("assemble")
def render_assemble_command(
    book_path: Path = typer.Argument(..., exists=True, file_okay=False),
    chapter: str | None = typer.Option(None, "--chapter", "-c"),
) -> None:
    """Assemble existing complete segment audio without calling the API."""
    plan, count = assemble_render(get_book(book_path), chapter=chapter)
    _print_render_issues(plan.issues)
    if plan.errors:
        raise typer.Exit(1)
    typer.echo(f"Assembled {count} segment(s).")


@render_app.command("status")
def render_status(book_path: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Show the latest render manifest status."""
    path = get_book(book_path).render_dir / "manifests" / "latest.json"
    if not path.exists():
        typer.echo("No render manifest found.")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        _fail(f"cannot read manifest: {error}")
    typer.echo(
        f"model={data.get('model', '-')} completed={data.get('completed', 0)} "
        f"failed={data.get('failed', 0)} "
        f"assembled={'yes' if data.get('assembled') else 'no'}"
    )


def _effective_segment_data(segment: object) -> dict[str, object]:
    data = segment_to_dict(segment, include_defaults=True)  # type: ignore[arg-type]
    if not data.get("review"):
        data.pop("review", None)
    return data


def _print_render_issues(issues: list[RenderIssueLike]) -> None:
    for issue in issues:
        typer.echo(str(issue), err=getattr(issue, "severity", "") == "ERROR")


class RenderIssueLike:
    severity: str


def _fail(message: str, code: int = 1) -> None:
    typer.echo(f"ERROR: {message}", err=True)
    raise typer.Exit(code)


if __name__ == "__main__":
    app()
