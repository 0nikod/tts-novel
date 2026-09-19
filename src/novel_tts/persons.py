from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .annotation_schema import SYSTEM_NAMES
from .models import Person


def load_persons(path: Path) -> list[Person]:
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("persons"), list):
        raise ValueError("root must be a mapping containing a persons list")
    extra = set(data) - {"persons"}
    if extra:
        raise ValueError("persons root has unsupported fields: " + ", ".join(sorted(extra)))

    people: list[Person] = []
    for index, item in enumerate(data["persons"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"person {index} must be a mapping")
        extra = set(item) - {"name", "aliases"}
        if extra:
            raise ValueError(
                f"person {index} has unsupported fields: " + ", ".join(sorted(map(str, extra)))
            )
        if "name" not in item:
            raise ValueError(f"person {index} is missing name")
        name = item["name"]
        aliases: Any = item.get("aliases", [])
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"person {index}: name must be a non-empty string")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ValueError(f"person {index}: aliases must be a list of non-empty strings")
        people.append(Person(name=name, aliases=list(aliases)))
    return people


def person_to_dict(person: Person) -> dict[str, Any]:
    return {"name": person.name, "aliases": person.aliases}


def save_persons(path: Path, people: list[Person]) -> None:
    path.write_text(
        yaml.safe_dump(
            {"persons": [person_to_dict(person) for person in people]},
            allow_unicode=True,
            sort_keys=False,
            width=1000,
        ),
        encoding="utf-8",
    )


def person_names(people: list[Person], *, include_system: bool = True) -> set[str]:
    names = {person.name for person in people}
    return names | set(SYSTEM_NAMES) if include_system else names


def alias_map(people: list[Person]) -> dict[str, str]:
    return {alias: person.name for person in people for alias in person.aliases}
