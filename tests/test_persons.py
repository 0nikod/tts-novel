from pathlib import Path

from novel_tts.models import Person
from novel_tts.persons import alias_map, load_persons, save_persons


def test_person_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "persons.yaml"
    people = [Person("小明", ["明明"], "main"), Person("小红", [], "secondary")]
    save_persons(path, people)
    loaded = load_persons(path)
    assert loaded == people
    assert alias_map(loaded) == {"明明": "小明"}
