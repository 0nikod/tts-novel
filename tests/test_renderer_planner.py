from pathlib import Path

from novel_tts.book import Book
from novel_tts.renderer.planner import build_render_plan

EXAMPLE_BOOK = Path(__file__).resolve().parents[1] / "books" / "example-book"


def test_example_scene_can_be_planned_without_api_access() -> None:
    plan, config = build_render_plan(Book(EXAMPLE_BOOK), scene_id="S0001")

    assert config is not None
    assert plan.errors == []
    assert len(plan.jobs) == 1
    assert plan.jobs[0].profile.model == "s2-pro"
    assert plan.jobs[0].name == "NARRATOR"


def test_full_example_is_blocked_by_review_and_unknown_speakers() -> None:
    plan, _config = build_render_plan(Book(EXAMPLE_BOOK))
    messages = [issue.message for issue in plan.errors]

    assert any("requires review" in message for message in messages)
    assert any("UNKNOWN speaker" in message for message in messages)


def test_same_scene_can_use_mimo_preset_profile() -> None:
    plan, _config = build_render_plan(
        Book(EXAMPLE_BOOK), profile_id="mimo-preset", scene_id="S0001"
    )

    assert plan.errors == []
    assert {job.voice.kind.value for job in plan.jobs} == {"preset"}
    assert {job.profile.model for job in plan.jobs} == {"mimo-v2.5-tts"}
