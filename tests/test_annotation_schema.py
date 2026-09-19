from pathlib import Path
from types import MappingProxyType
from typing import get_args

import pytest
import yaml

from novel_tts.annotation_schema import (
    NARRATOR_NAME,
    PERSON_ROLES,
    REVIEW_REASONS,
    STYLE_FIELDS,
    STYLE_VALUES,
    SYSTEM_NAMES,
    TEXT_TYPES,
    UNKNOWN_NAME,
    PersonRole,
    ReviewReason,
    StyleField,
    StyleValue,
    TextType,
)
from novel_tts.renderer.style import (
    FISH_PACE,
    FISH_TAGS,
    FISH_VOLUME,
    MIMO_ACTIONS,
    MIMO_TERMS,
    load_style_mappings,
    validate_provider_default_mappings,
)

ANNOTATION_SCHEMA_PATH = Path(__file__).parents[1] / "docs" / "annotation.schema.yaml"


def test_structural_annotation_schema_is_yaml_and_keeps_style_optional() -> None:
    schema = yaml.safe_load(ANNOTATION_SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["$id"].startswith("https://")
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["chapter", "segments"]
    segment = schema["$defs"]["segment"]
    assert set(segment["required"]) == {"line", "name", "type"}
    assert "style" not in segment["required"]
    assert "scene_id" not in segment["properties"]
    style = schema["$defs"]["style"]
    assert style["minProperties"] == 1
    assert "style-value-or-null" not in schema["$defs"]
    assert style["additionalProperties"] is False
    assert all(field.get("type") == "string" for field in style["properties"].values())


def test_annotation_schema_has_exact_canonical_vocabulary() -> None:
    assert TEXT_TYPES == ("narration", "dialogue", "thought")
    assert PERSON_ROLES == ("main", "secondary", "minor")
    assert NARRATOR_NAME == "NARRATOR"
    assert UNKNOWN_NAME == "UNKNOWN"
    assert SYSTEM_NAMES == (NARRATOR_NAME, UNKNOWN_NAME)
    assert REVIEW_REASONS == (
        "ambiguous_speaker",
        "ambiguous_type",
        "ambiguous_style",
        "ambiguous_scene",
        "unknown_character",
        "preprocess_error",
    )
    assert STYLE_FIELDS == (
        "emotion",
        "delivery",
        "volume",
        "pace",
        "vocal_action_before",
        "vocal_action_after",
    )
    assert dict(STYLE_VALUES) == {
        "emotion": ("angry", "calm", "excited", "happy", "nervous", "sad", "shocked"),
        "delivery": ("scolding", "shout", "whisper"),
        "volume": ("high", "low"),
        "pace": ("fast", "slow"),
        "vocal_action_before": ("laugh", "sigh", "deep_breath"),
        "vocal_action_after": ("laugh", "sigh", "deep_breath"),
    }
    assert isinstance(STYLE_VALUES, MappingProxyType)


def test_static_literal_types_match_runtime_yaml_vocabulary() -> None:
    assert get_args(TextType) == TEXT_TYPES
    assert get_args(PersonRole) == PERSON_ROLES
    assert get_args(ReviewReason) == REVIEW_REASONS
    assert get_args(StyleField) == STYLE_FIELDS
    assert set(get_args(StyleValue)) == {
        value for values in STYLE_VALUES.values() for value in values
    }


def test_renderer_defaults_do_not_extend_annotation_taxonomy() -> None:
    validate_provider_default_mappings("fish tags", FISH_TAGS)
    validate_provider_default_mappings("fish controls", {"pace": FISH_PACE, "volume": FISH_VOLUME})
    validate_provider_default_mappings("mimo terms", MIMO_TERMS)
    validate_provider_default_mappings(
        "mimo actions",
        {"vocal_action_before": MIMO_ACTIONS, "vocal_action_after": MIMO_ACTIONS},
    )


def test_renderer_default_validation_rejects_noncanonical_value() -> None:
    with pytest.raises(ValueError, match="outside STYLE_VALUES"):
        validate_provider_default_mappings("test", {"emotion": {"invented": "output"}})


def test_load_style_mappings_accepts_canonical_remaps(tmp_path) -> None:
    render_root = tmp_path / "render"
    render_root.mkdir()
    (render_root / "styles.yaml").write_text(
        "mimo:\n"
        "  emotion:\n"
        "    sad: 低落、沮丧\n"
        "fish_audio:\n"
        "  pace:\n"
        "    slow: 0.75\n"
        "  volume_db:\n"
        "    low: -4\n",
        encoding="utf-8",
    )

    assert load_style_mappings(render_root) == {
        "mimo": {"emotion": {"sad": "低落、沮丧"}},
        "fish_audio": {"pace": {"slow": 0.75}, "volume_db": {"low": -4}},
    }


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("other: {}\n", "unknown provider 'other'"),
        ("mimo:\n  invented: {}\n", "unknown style field 'invented'"),
        (
            "mimo:\n  emotion:\n    dejected: 低落\n",
            "non-canonical annotation value 'dejected'",
        ),
        ("mimo:\n  emotion:\n    sad: 1\n", "must be a non-empty string"),
        ("fish_audio:\n  pace:\n    slow: fast\n", "must be a finite number"),
        ("fish_audio:\n  pace:\n    slow: .nan\n", "must be a finite number"),
    ],
)
def test_load_style_mappings_rejects_invalid_remaps(tmp_path, content: str, message: str) -> None:
    render_root = tmp_path / "render"
    render_root.mkdir()
    (render_root / "styles.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_style_mappings(render_root)
