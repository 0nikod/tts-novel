from __future__ import annotations

import re
from pathlib import Path

from .models import Person, SYSTEM_NAMES


HEADING_RE = re.compile(r"^#\s+(.+?)\s*$")
ALIAS_RE = re.compile(r"^\s*-\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$")


def load_persons(path: Path) -> list[Person]:
    if not path.exists():
        return []
    people: list[Person] = []
    current: Person | None = None
    field: str | None = None

    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        heading = HEADING_RE.match(raw)
        if heading:
            name = heading.group(1).strip()
            if not name:
                raise ValueError(f"line {number}: empty person name")
            current = Person(name=name)
            people.append(current)
            field = None
            continue
        if not raw.strip() or raw.lstrip().startswith("<!--"):
            continue
        if current is None:
            raise ValueError(f"line {number}: content before first person heading")
        match = FIELD_RE.match(raw)
        if match:
            field, value = match.groups()
            if field in {"speaker_id", "speaker-id", "speaker_token", "speaker-token"}:
                raise ValueError(f"line {number}: {field} must not be persisted")
            if field == "aliases":
                if value not in ("", "[]"):
                    raise ValueError(f"line {number}: aliases must be a list")
                current.aliases = []
            elif field == "role":
                current.role = value or None
            # Unknown fields are tolerated so confirmed metadata can be extended.
            continue
        alias = ALIAS_RE.match(raw)
        if alias and field == "aliases":
            current.aliases.append(alias.group(1).strip())
            continue
        raise ValueError(f"line {number}: unsupported persons.md syntax")
    return people


def save_persons(path: Path, people: list[Person]) -> None:
    sections: list[str] = []
    for person in people:
        aliases = "aliases: []" if not person.aliases else "aliases:\n" + "\n".join(
            f"  - {alias}" for alias in person.aliases
        )
        role = person.role or "unknown"
        sections.append(f"# {person.name}\n\n{aliases}\n\nrole: {role}\n")
    path.write_text("\n".join(sections), encoding="utf-8")


def person_names(people: list[Person]) -> set[str]:
    return {person.name for person in people} | SYSTEM_NAMES


def alias_map(people: list[Person]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for person in people:
        for alias in person.aliases:
            aliases[alias] = person.name
    return aliases
