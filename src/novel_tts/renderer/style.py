from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..annotation_schema import STYLE_FIELDS, STYLE_VALUES
from .models import CompiledStyle


def load_style_mappings(render_root: Path) -> dict[str, dict[str, Any]]:
    """Load optional semantic-value overrides for the private model."""
    path = render_root / "styles.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML in {path}: {error}") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("render/styles.yaml root must be a mapping")

    mappings: dict[str, dict[str, Any]] = {}
    for field, raw_values in data.items():
        if field not in STYLE_FIELDS:
            raise ValueError(f"render/styles.yaml has unknown style field {field!r}")
        if not isinstance(raw_values, dict):
            raise ValueError(f"render/styles.yaml {field} must be a mapping")
        values: dict[str, Any] = {}
        for value, compiled in raw_values.items():
            if value not in STYLE_VALUES[field]:
                allowed = ", ".join(STYLE_VALUES[field])
                raise ValueError(
                    f"render/styles.yaml {field} has non-canonical value {value!r}; "
                    f"allowed values: {allowed}"
                )
            if compiled is None:
                raise ValueError(f"render/styles.yaml {field}.{value} must not be null")
            values[value] = compiled
        mappings[field] = values
    return mappings


def compile_style(
    style: dict[str, str] | None,
    mappings: dict[str, dict[str, Any]] | None = None,
) -> CompiledStyle:
    """Translate provider-neutral style to the private model representation.

    By default the custom API receives the canonical field and value unchanged.
    ``styles.yaml`` may replace individual values without changing annotations.
    """
    if not style:
        return CompiledStyle()
    custom = mappings or {}
    return CompiledStyle(
        {field: custom.get(field, {}).get(value, value) for field, value in style.items()}
    )
