from __future__ import annotations

import json
from pathlib import Path

import typer

from .annotations import load_annotation
from .book import Book
from .preprocessing import preprocess_file, read_processed
from .validation import validate_book


app = typer.Typer(
    no_args_is_help=True,
    help="Prepare and validate novel text for TTS annotation.",
)


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
            [book.resolve_source_chapter(chapter)] if chapter is not None else book.source_chapters()
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
    output_format: str = typer.Option(
        "text", "--format", help="Output format: text or json"
    ),
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
    except ValueError as error:
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
            if not segment.review:
                continue
            total += 1
            typer.echo(
                f"[{source.stem}:{segment.line.format()}] "
                f"{segment.review_reason or 'unspecified'} | "
                f"{segment.name}/{segment.type} | {segment.scene_id}"
            )
            for number in range(segment.line.start, segment.line.end + 1):
                typer.echo(f"  {number}-{text_by_line.get(number, '<missing>')}")
    typer.echo(f"Total review items: {total}")


if __name__ == "__main__":
    app()
