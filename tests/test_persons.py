from pathlib import Path

import pytest

from novel_tts.models import Person
from novel_tts.persons import alias_map, load_persons, save_persons


def test_person_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "persons.yaml"
    people = [
        Person("小明", "main", ["明明"]),
        Person("小红", "secondary", []),
    ]
    save_persons(path, people)
    loaded = load_persons(path)
    assert loaded == people
    assert alias_map(loaded) == {"明明": "小明"}


@pytest.mark.parametrize(
    ("role_yaml", "expected"),
    [("protagonist", "'protagonist'"), ("null", "None")],
)
def test_load_persons_rejects_invalid_role(tmp_path: Path, role_yaml: str, expected: str) -> None:
    path = tmp_path / "persons.yaml"
    path.write_text(
        f"persons:\n  - name: 小明\n    aliases: []\n    role: {role_yaml}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=rf"invalid role {expected}.*main, secondary, minor"):
        load_persons(path)
