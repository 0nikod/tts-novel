from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal

import yaml

# Static aliases improve application typing. Tests keep them synchronized with the
# runtime YAML vocabulary, which remains the canonical data source.
TextType = Literal["narration", "dialogue", "thought"]
PersonRole = Literal["main", "secondary", "minor"]
ReviewReason = Literal[
    "ambiguous_speaker",
    "ambiguous_type",
    "ambiguous_style",
    "ambiguous_scene",
    "unknown_character",
    "preprocess_error",
]
StyleField = Literal[
    "emotion",
    "delivery",
    "volume",
    "pace",
    "vocal_action_before",
    "vocal_action_after",
]
StyleValue = Literal[
    "angry",
    "calm",
    "excited",
    "happy",
    "nervous",
    "sad",
    "shocked",
    "scolding",
    "shout",
    "whisper",
    "high",
    "low",
    "fast",
    "slow",
    "laugh",
    "sigh",
    "deep_breath",
]

_SCHEMA_KEYS = {
    "text_types",
    "person_roles",
    "system_names",
    "review_reasons",
    "style_values",
}


def _load_schema() -> dict[str, Any]:
    path = Path(__file__).with_name("annotation_schema.yaml")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(f"cannot load annotation vocabulary from {path}: {error}") from error
    if not isinstance(data, dict):
        raise RuntimeError(f"annotation vocabulary in {path} must be a mapping")
    unknown = set(data) - _SCHEMA_KEYS
    missing = _SCHEMA_KEYS - set(data)
    if unknown:
        raise RuntimeError(
            "annotation vocabulary contains unknown fields: " + ", ".join(sorted(map(str, unknown)))
        )
    if missing:
        raise RuntimeError("annotation vocabulary is missing fields: " + ", ".join(sorted(missing)))
    return data


def _string_tuple(schema: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = schema.get(key)
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value for value in values)
    ):
        raise RuntimeError(f"annotation vocabulary {key!r} must be a non-empty string list")
    if len(set(values)) != len(values):
        raise RuntimeError(f"annotation vocabulary {key!r} must not contain duplicates")
    return tuple(values)


_SCHEMA = _load_schema()

# Tuples provide deterministic iteration for all annotation consumers.
TEXT_TYPES: Final[tuple[str, ...]] = _string_tuple(_SCHEMA, "text_types")
PERSON_ROLES: Final[tuple[str, ...]] = _string_tuple(_SCHEMA, "person_roles")
_raw_system_names = _SCHEMA["system_names"]
if not isinstance(_raw_system_names, dict):
    raise RuntimeError("annotation vocabulary 'system_names' must be a mapping")
if set(_raw_system_names) != {"narrator", "unknown"} or any(
    not isinstance(value, str) or not value for value in _raw_system_names.values()
):
    raise RuntimeError(
        "annotation vocabulary 'system_names' must map narrator and unknown to non-empty strings"
    )
if len(set(_raw_system_names.values())) != len(_raw_system_names):
    raise RuntimeError("annotation system names must be distinct")
NARRATOR_NAME: Final[str] = _raw_system_names["narrator"]
UNKNOWN_NAME: Final[str] = _raw_system_names["unknown"]
SYSTEM_NAMES: Final[tuple[str, ...]] = (NARRATOR_NAME, UNKNOWN_NAME)
REVIEW_REASONS: Final[tuple[str, ...]] = _string_tuple(_SCHEMA, "review_reasons")

_raw_style_values = _SCHEMA["style_values"]
if not isinstance(_raw_style_values, dict) or not _raw_style_values:
    raise RuntimeError("annotation vocabulary 'style_values' must be a non-empty mapping")
STYLE_VALUES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        field: _string_tuple(_raw_style_values, field)
        for field in _raw_style_values
        if isinstance(field, str) and field
    }
)
if len(STYLE_VALUES) != len(_raw_style_values):
    raise RuntimeError("annotation style field names must be non-empty strings")
STYLE_FIELDS: Final[tuple[str, ...]] = tuple(STYLE_VALUES)
