import wave
from pathlib import Path

from novel_tts.book import Book
from novel_tts.renderer.cache import cache_path
from novel_tts.renderer.config import render_target
from novel_tts.renderer.http import TTSRequestError
from novel_tts.renderer.models import AudioResult, CompiledStyle, RenderProfile, Voice
from novel_tts.renderer.planner import (
    build_render_plan,
    make_cache_key,
    split_text,
    style_for_chunk,
)
from novel_tts.renderer.service import run_render
from novel_tts.renderer.style import compile_style


def make_book(tmp_path: Path, annotation: str | None = None) -> Book:
    book = Book(tmp_path / "book")
    book.initialize()
    (book.source_dir / "001.txt").write_text("旁白\n“你好”\n结尾\n", encoding="utf-8")
    (book.processed_dir / "001.txt").write_text("1-旁白\n2-“你好”\n3-结尾\n", encoding="utf-8")
    book.persons_path.write_text("persons:\n  - name: 小明\n    aliases: []\n", encoding="utf-8")
    (book.annotations_dir / "001.yaml").write_text(
        annotation or "segments:\n  - line: 2\n    name: 小明\n", encoding="utf-8"
    )
    book.render_config_path.write_text(
        "target: test-main\n"
        "default_profile: custom-main\n"
        "profiles:\n"
        "  custom-main:\n"
        "    provider: custom\n"
        "    endpoint: http://127.0.0.1:8000/v1/tts\n"
        "    model: test-model\n"
        "    api_key_env: TEST_KEY\n"
        "    concurrency: 1\n"
        "    retries: 0\n"
        "output:\n  sample_rate: 24000\n  channels: 1\n  final_format: wav\n"
        "execution:\n  max_chars_per_request: 200\n",
        encoding="utf-8",
    )
    book.voices_path.write_text(
        "voices:\n  narrator:\n    reference_id: n1\n  hero:\n    reference_id: h1\n",
        encoding="utf-8",
    )
    book.voice_used_path.write_text(
        "voices:\n  NARRATOR: narrator\n  小明: hero\n", encoding="utf-8"
    )
    return book


def configure_mixed(book: Book) -> None:
    book.render_config_path.write_text(
        "target: mixed-test\n"
        "default_profile: custom-main\n"
        "profiles:\n"
        "  custom-main:\n"
        "    provider: custom\n"
        "    endpoint: https://custom.test/main\n"
        "    model: main-model\n"
        "    api_key_env: MAIN_KEY\n"
        "  custom-alt:\n"
        "    provider: custom\n"
        "    endpoint: https://custom.test/alt\n"
        "    model: alt-model\n"
        "    api_key_env: ALT_KEY\n",
        encoding="utf-8",
    )
    book.voices_path.write_text(
        "voices:\n"
        "  narrator:\n    reference_id: n1\n"
        "  hero:\n    profile: custom-alt\n    reference_id: h1\n",
        encoding="utf-8",
    )


def write_wave(path: Path, frames: int = 100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * frames)


def test_effective_annotations_enter_planner_without_scenes(tmp_path: Path) -> None:
    plan, config = build_render_plan(make_book(tmp_path))
    assert config is not None
    assert plan.errors == []
    assert [(job.line_start, job.line_end, job.name) for job in plan.jobs] == [
        (1, 1, "NARRATOR"),
        (2, 2, "小明"),
        (3, 3, "NARRATOR"),
    ]


def test_mixed_profile_plan_selects_profile_per_voice(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    configure_mixed(book)

    plan, config = build_render_plan(book)

    assert config is not None
    assert plan.errors == []
    assert [(job.name, job.profile.id) for job in plan.jobs] == [
        ("NARRATOR", "custom-main"),
        ("小明", "custom-alt"),
        ("NARRATOR", "custom-main"),
    ]


def test_missing_casting_and_unknown_block_render(tmp_path: Path) -> None:
    book = make_book(tmp_path / "missing")
    book.voice_used_path.write_text("voices:\n  NARRATOR: narrator\n", encoding="utf-8")
    plan, _ = build_render_plan(book)
    assert any(
        "Missing voices" in issue.message and "小明" in issue.message for issue in plan.errors
    )

    unknown = make_book(
        tmp_path / "unknown",
        "segments:\n  - line: 2\n    name: UNKNOWN\n    review: true\n",
    )
    plan, _ = build_render_plan(unknown)
    assert any("UNKNOWN speaker cannot be rendered" in issue.message for issue in plan.errors)


def test_style_compiler_and_cache_key_inputs(tmp_path: Path) -> None:
    style = {
        "direction": "低声、迟疑，后半句逐渐疲惫。",
        "tags_before": ["紧张", "深呼吸"],
        "tags_after": ["苦笑"],
    }
    custom = compile_style("custom", "正文", style)
    assert custom.text == "正文"
    assert custom.instruction == style["direction"]
    assert custom.values == style

    mimo = compile_style("mimo", "正文", style)
    assert mimo.text == "（紧张｜深呼吸）正文（苦笑）"
    assert mimo.instruction == "低声、迟疑，后半句逐渐疲惫。"
    _, config = build_render_plan(make_book(tmp_path / "book"))
    assert config is not None
    profile = config.profiles[config.default_profile]
    voice = Voice("v", profile.id, {"reference_id": "one"})
    base = make_cache_key(
        config=config,
        profile=profile,
        text="a",
        voice=voice,
        style=CompiledStyle(text="a"),
    )
    assert base != make_cache_key(
        config=config,
        profile=profile,
        text="b",
        voice=voice,
        style=CompiledStyle(text="b"),
    )
    assert base != make_cache_key(
        config=config,
        profile=profile,
        text="a",
        voice=Voice("other", profile.id, {"reference_id": "other"}),
        style=CompiledStyle(text="a"),
    )
    assert base != make_cache_key(
        config=config,
        profile=profile,
        text="a",
        voice=voice,
        style=CompiledStyle(text="a", instruction="慢慢说"),
    )


def test_segment_boundary_tags_are_not_repeated_across_chunks_or_scenes() -> None:
    style = {
        "direction": "先克制，后疲惫。",
        "tags_before": ["深呼吸"],
        "tags_after": ["苦笑"],
    }
    assert style_for_chunk(style, 1, 2) == {
        "direction": "先克制，后疲惫。",
        "tags_before": ["深呼吸"],
    }
    assert style_for_chunk(style, 2, 2) == {
        "direction": "先克制，后疲惫。",
        "tags_after": ["苦笑"],
    }
    assert style_for_chunk(style, 1, 1, last_piece=False) == {
        "direction": "先克制，后疲惫。",
        "tags_before": ["深呼吸"],
    }
    assert style_for_chunk(style, 1, 1, first_piece=False) == {
        "direction": "先克制，后疲惫。",
        "tags_after": ["苦笑"],
    }


def test_text_split_preserves_text() -> None:
    text = "第一句。第二句很长，第三句。"
    chunks = split_text(text, 8)
    assert "".join(chunks) == text
    assert all(len(chunk) <= 8 for chunk in chunks)


class FailingBackend:
    calls = 0

    def synthesize(self, **_kwargs: object) -> AudioResult:
        self.calls += 1
        raise AssertionError("cache hit should not call the backend")


class InvalidAudioBackend:
    def synthesize(self, **_kwargs: object) -> AudioResult:
        return AudioResult(b"not audio")


class RequestFailingBackend:
    def synthesize(self, **_kwargs: object) -> AudioResult:
        raise TTSRequestError("service unavailable", attempts=3, elapsed_ms=42)


class RecordingBackend:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def synthesize(self, **_kwargs: object) -> AudioResult:
        self.calls += 1
        return AudioResult(b"raw")

    def close(self) -> None:
        self.closed = True


def test_cache_hit_does_not_call_api_and_assembles(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    plan, config = build_render_plan(book)
    assert config is not None
    for job in plan.jobs:
        write_wave(cache_path(config.root, job.cache_key))
    backend = FailingBackend()

    _, manifest = run_render(book, backend=backend)

    assert backend.calls == 0
    assert manifest["failed"] == 0
    assert manifest["assembled"] is True
    assert (book.render_dir / "output" / render_target(config) / "book.wav").exists()


def test_mixed_profile_run_uses_independent_runners(tmp_path: Path, monkeypatch) -> None:
    book = make_book(tmp_path)
    configure_mixed(book)
    runners: dict[str, RecordingBackend] = {}

    def create_runner(_render_root: Path, profile: RenderProfile) -> RecordingBackend:
        runner = RecordingBackend()
        runners[profile.id] = runner
        return runner

    def normalize(_source: Path, destination: Path, **_kwargs: object) -> None:
        write_wave(destination)

    monkeypatch.setattr("novel_tts.renderer.service.create_runner", create_runner)
    monkeypatch.setattr("novel_tts.renderer.service.normalize_audio", normalize)

    _, manifest = run_render(book)

    assert runners["custom-main"].calls == 2
    assert runners["custom-alt"].calls == 1
    assert all(runner.closed for runner in runners.values())
    assert set(manifest["profiles"]) == {"custom-main", "custom-alt"}
    assert manifest["assembled"] is True


def test_failed_request_keeps_retry_metadata(tmp_path: Path) -> None:
    book = make_book(tmp_path)

    _, manifest = run_render(book, backend=RequestFailingBackend())

    assert manifest["failed"] == 3
    assert all(entry["attempts"] == 3 for entry in manifest["jobs"])
    assert all(entry["elapsed_ms"] == 42 for entry in manifest["jobs"])


def test_failed_job_never_assembles_final_audio(tmp_path: Path, monkeypatch) -> None:
    book = make_book(tmp_path)
    monkeypatch.setattr(
        "novel_tts.renderer.service.normalize_audio",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad audio")),
    )

    _, config = build_render_plan(book)
    assert config is not None
    _, manifest = run_render(book, backend=InvalidAudioBackend())

    assert manifest["failed"]
    assert manifest["assembled"] is False
    assert not (book.render_dir / "output" / render_target(config) / "book.wav").exists()
