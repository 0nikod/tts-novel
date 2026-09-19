import wave
from pathlib import Path

from novel_tts.book import Book
from novel_tts.renderer.cache import cache_path
from novel_tts.renderer.models import AudioResult, CompiledStyle, Voice
from novel_tts.renderer.planner import build_render_plan, make_cache_key, split_text
from novel_tts.renderer.service import run_render
from novel_tts.renderer.style import compile_style, load_style_mappings


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
        "endpoint: http://127.0.0.1:8000/v1/tts\n"
        "model: test-model\n"
        "api_key_env: TEST_KEY\n"
        "concurrency: 1\n"
        "retries: 0\n"
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
    render = tmp_path / "render"
    render.mkdir()
    (render / "styles.yaml").write_text("emotion:\n  nervous: tense\n", encoding="utf-8")
    assert compile_style({"emotion": "nervous"}, load_style_mappings(render)).values == {
        "emotion": "tense"
    }
    _, config = build_render_plan(make_book(tmp_path / "book"))
    assert config is not None
    voice = Voice("v", {"reference_id": "one"})
    base = make_cache_key(config=config, text="a", voice=voice, style=CompiledStyle())
    assert base != make_cache_key(config=config, text="b", voice=voice, style=CompiledStyle())
    assert base != make_cache_key(
        config=config, text="a", voice=Voice("other"), style=CompiledStyle()
    )
    assert base != make_cache_key(
        config=config, text="a", voice=voice, style=CompiledStyle({"pace": "slow"})
    )


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
    assert (book.render_dir / "output" / "book.wav").exists()


def test_failed_job_never_assembles_final_audio(tmp_path: Path, monkeypatch) -> None:
    book = make_book(tmp_path)
    monkeypatch.setattr(
        "novel_tts.renderer.service.normalize_audio",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad audio")),
    )

    _, manifest = run_render(book, backend=InvalidAudioBackend())

    assert manifest["failed"]
    assert manifest["assembled"] is False
    assert not (book.render_dir / "output" / "book.wav").exists()
