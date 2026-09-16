from pathlib import Path

from novel_tts.annotations import merge_adjacent_segments
from novel_tts.models import ChapterLineRange, LineRange, Scene, Segment
from novel_tts.scenes import load_scenes, next_scene_id, save_scenes


def test_scene_round_trip_and_next_id(tmp_path: Path) -> None:
    path = tmp_path / "scenes.yaml"
    scenes = [
        Scene(
            "S0001",
            [ChapterLineRange("001", LineRange(1, 8)), ChapterLineRange("002", LineRange(1, 2))],
            "连续事件",
        )
    ]
    save_scenes(path, scenes)
    assert load_scenes(path) == scenes
    assert next_scene_id(scenes) == "S0002"


def test_merge_adjacent_segments() -> None:
    one = Segment(LineRange(1, 1), "小明", "dialogue", None, "S0001")
    two = Segment(LineRange(2, 3), "小明", "dialogue", None, "S0001")
    three = Segment(LineRange(4, 4), "小红", "dialogue", None, "S0001")
    merged = merge_adjacent_segments([one, two, three])
    assert [segment.line for segment in merged] == [LineRange(1, 3), LineRange(4, 4)]
