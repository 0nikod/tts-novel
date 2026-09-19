import json
import wave
from pathlib import Path

from novel_tts.book import Book
from novel_tts.renderer.planner import build_render_plan, split_text
from novel_tts.renderer.service import run_render


def _make_render_book(tmp_path: Path) -> Book:
    book_root = tmp_path / "book"
    for directory in ("source", "processed", "annotations", "render"):
        (book_root / directory).mkdir(parents=True, exist_ok=True)
    (book_root / "source" / "01.txt").write_text("叙述。\n“你好！”\n", encoding="utf-8")
    (book_root / "processed" / "01.txt").write_text("1-叙述。\n2-“你好！”\n", encoding="utf-8")
    (book_root / "persons.yaml").write_text(
        "persons:\n  - name: EXTRA\n    aliases: []\n    role: minor\n",
        encoding="utf-8",
    )
    (book_root / "scenes.yaml").write_text(
        "scenes:\n  - id: S0001\n    line: '01:1-2'\n    summary: 测试场景\n",
        encoding="utf-8",
    )
    (book_root / "annotations" / "01.yaml").write_text(
        "chapter: 1\n"
        "segments:\n"
        "  - line: 1\n"
        "    name: NARRATOR\n"
        "    type: narration\n"
        "    style: null\n"
        "    scene_id: S0001\n"
        "  - line: 2\n"
        "    name: EXTRA\n"
        "    type: dialogue\n"
        "    style: null\n"
        "    scene_id: S0001\n",
        encoding="utf-8",
    )
    (book_root / "render" / "config.yaml").write_text(
        "profiles:\n"
        "  fish:\n"
        "    provider: fish_audio\n"
        "    model: s2-pro\n"
        "    api_key_env: NOVEL_TTS_TEST_MISSING_API_KEY\n"
        "    request:\n"
        "      format: wav\n"
        "  mimo:\n"
        "    provider: mimo\n"
        "    model: mimo-v2.5-tts\n"
        "    api_key_env: MIMO_API_KEY\n"
        "    request:\n"
        "      format: wav\n",
        encoding="utf-8",
    )
    (book_root / "render" / "voices.yaml").write_text(
        "voices:\n"
        "  NARRATOR:\n"
        "    fish:\n"
        "      profile: fish\n"
        "      kind: saved_reference\n"
        "      reference_id: narrator\n"
        "    mimo:\n"
        "      profile: mimo\n"
        "      kind: preset\n"
        "      voice: 白桦\n"
        "  EXTRA:\n"
        "    fish:\n"
        "      profile: fish\n"
        "      kind: saved_reference\n"
        "      reference_id: narrator\n"
        "    mimo:\n"
        "      profile: mimo\n"
        "      kind: preset\n"
        "      voice: 白桦\n",
        encoding="utf-8",
    )
    (book_root / "render" / "voice_used.yaml").write_text(
        "default_profile: fish\nvoices: {}\n", encoding="utf-8"
    )
    (book_root / "render" / "styles.yaml").write_text("{}\n", encoding="utf-8")
    return Book(book_root)


def test_scene_can_be_planned_without_api_access(tmp_path: Path) -> None:
    plan, config = build_render_plan(_make_render_book(tmp_path), scene_id="S0001")

    assert config is not None
    assert plan.errors == []
    assert len(plan.jobs) == 2
    assert {job.profile.model for job in plan.jobs} == {"s2-pro"}


def test_full_book_can_be_planned_with_extra_fallback(tmp_path: Path) -> None:
    plan, _config = build_render_plan(_make_render_book(tmp_path))

    assert plan.errors == []
    assert len(plan.jobs) == 2
    assert "EXTRA" in {job.name for job in plan.jobs}


def test_same_scene_can_use_mimo_preset_profile(tmp_path: Path) -> None:
    plan, _config = build_render_plan(
        _make_render_book(tmp_path), profile_id="mimo", scene_id="S0001"
    )

    assert plan.errors == []
    assert {job.voice.kind.value for job in plan.jobs} == {"preset"}
    assert {job.profile.model for job in plan.jobs} == {"mimo-v2.5-tts"}


def test_structural_annotation_errors_stop_planning_without_exception(tmp_path: Path) -> None:
    book = _make_render_book(tmp_path)
    annotation_path = book.annotations_dir / "01.yaml"
    content = annotation_path.read_text(encoding="utf-8")
    annotation_path.write_text(
        content.replace("    style: null\n", "    style:\n      emotion: []\n", 1),
        encoding="utf-8",
    )

    plan, config = build_render_plan(book)

    assert config is None
    assert plan.jobs == []
    assert any("style.emotion must be a string or null" in issue.message for issue in plan.errors)


def test_text_split_is_bounded_and_lossless() -> None:
    text = "第一句很长。第二句也很长！第三句仍然很长，最后结束。"

    chunks = split_text(text, 12)

    assert "".join(chunks) == text
    assert all(0 < len(chunk) <= 12 for chunk in chunks)
    assert len(chunks) > 1


def test_output_normalization_changes_cache_key(tmp_path: Path) -> None:
    book = _make_render_book(tmp_path)
    first, _config = build_render_plan(book)
    config_path = book.root / "render" / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "output:\n  sample_rate: 48000\n  channels: 1\n  sample_format: s16\n",
        encoding="utf-8",
    )
    second, _config = build_render_plan(book)

    assert [job.cache_key for job in first.jobs] != [job.cache_key for job in second.jobs]


def test_failed_segment_does_not_create_partial_book_by_default(tmp_path: Path) -> None:
    book = _make_render_book(tmp_path)
    plan, config = build_render_plan(book)
    assert config is not None
    first_cache = config.root / "cache" / f"{plan.jobs[0].cache_key}.wav"
    _write_silence(first_cache)
    output = config.root / "output" / "fish"
    output.mkdir(parents=True)
    (output / "book.wav").write_bytes(b"stale")

    _plan, manifest = run_render(book)

    assert manifest["completed"] == 1
    assert manifest["failed"] == 1
    assert manifest["assembled"] is False
    assert not (output / "book.wav").exists()


def test_legacy_cache_is_migrated_without_api_requests(tmp_path: Path) -> None:
    book = _make_render_book(tmp_path)
    plan, config = build_render_plan(book)
    assert config is not None
    for job in plan.jobs:
        assert job.legacy_cache_key is not None
        _write_silence(config.root / "cache" / f"{job.legacy_cache_key}.wav")

    _plan, manifest = run_render(book)

    assert manifest["failed"] == 0
    assert {segment["cache"] for segment in manifest["segments"]} == {"migrated"}


def test_complete_cached_render_writes_reproducibility_snapshots(tmp_path: Path) -> None:
    book = _make_render_book(tmp_path)
    plan, config = build_render_plan(book)
    assert config is not None
    for job in plan.jobs:
        _write_silence(config.root / "cache" / f"{job.cache_key}.wav")

    _plan, manifest = run_render(book)

    output = config.root / "output" / "fish"
    snapshot_sources = {item["source"] for item in manifest["snapshots"]}
    disk_manifest = json.loads((config.root / "manifests" / "fish.json").read_text())
    assert manifest["assembled"] is True
    assert (output / "book.wav").is_file()
    assert {
        "render/config.yaml",
        "render/voices.yaml",
        "render/voice_used.yaml",
        "render/styles.yaml",
        "persons.yaml",
        "scenes.yaml",
        "annotations/01.yaml",
        "processed/01.txt",
        "source/01.txt",
    } <= snapshot_sources
    assert disk_manifest["segments"][0]["voice"]["reference_id"] == "narrator"


def _write_silence(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 240)
