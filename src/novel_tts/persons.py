from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from .annotation_schema import PERSON_ROLES, SYSTEM_NAMES, PersonRole
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

    people: list[Person] = []
    for index, item in enumerate(data["persons"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"person {index} must be a mapping")
        extra = set(item) - {"name", "aliases", "role"}
        if extra:
            raise ValueError(
                f"person {index} has unsupported fields: " + ", ".join(sorted(map(str, extra)))
            )
        missing = {"name", "aliases", "role"} - set(item)
        if missing:
            raise ValueError(
                f"person {index} is missing fields: " + ", ".join(sorted(map(str, missing)))
            )

        name = item["name"]
        aliases = item["aliases"]
        role = item["role"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"person {index}: name must be a non-empty string")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ValueError(f"person {index}: aliases must be a list of non-empty strings")
        if role not in PERSON_ROLES:
            allowed = ", ".join(PERSON_ROLES)
            raise ValueError(f"person {index}: invalid role {role!r}; allowed values: {allowed}")
        people.append(Person(name=name, aliases=aliases, role=cast("PersonRole", role)))
    return people


def person_to_dict(person: Person) -> dict[str, Any]:
    return {
        "name": person.name,
        "aliases": person.aliases,
        "role": person.role,
    }


def save_persons(path: Path, people: list[Person]) -> None:
    data = {"persons": [person_to_dict(person) for person in people]}
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )


def person_names(people: list[Person]) -> set[str]:
    return {person.name for person in people} | set(SYSTEM_NAMES)


def alias_map(people: list[Person]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for person in people:
        for alias in person.aliases:
            aliases[alias] = person.name
    return aliases
