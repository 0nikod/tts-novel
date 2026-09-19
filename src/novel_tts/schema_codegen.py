from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from .annotation_schema import STYLE_SCHEMA, SYSTEM_NAMES, TEXT_TYPES

_GENERATED_HEADER = (
    "# Generated from src/novel_tts/annotation_schema.py.\n# Do not edit manually.\n"
)


def annotation_json_schema() -> dict[str, Any]:
    style_properties: dict[str, Any] = {}
    for field, spec in STYLE_SCHEMA.items():
        if spec["kind"] == "direction":
            style_properties[field] = {
                "type": "string",
                "minLength": 1,
                "description": spec["description"],
            }
        else:
            style_properties[field] = {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
                "description": spec["description"],
            }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.invalid/novel-tts/annotation.schema.yaml",
        "title": "tts-novel sparse annotation",
        "description": (
            "Provider-neutral sparse semantic annotation. Uncovered processed lines are "
            "NARRATOR/narration at runtime."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": ["segments"],
        "properties": {
            "segments": {
                "type": "array",
                "items": {"$ref": "#/$defs/segment"},
            }
        },
        "$defs": {
            "line-range": {
                "oneOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "string", "pattern": "^[1-9][0-9]*-[1-9][0-9]*$"},
                ]
            },
            "style": {
                "type": "object",
                "additionalProperties": False,
                "minProperties": 1,
                "properties": style_properties,
            },
            "segment": {
                "type": "object",
                "additionalProperties": False,
                "required": ["line", "name"],
                "properties": {
                    "line": {"$ref": "#/$defs/line-range"},
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Canonical person name or system name: " + ", ".join(SYSTEM_NAMES) + "."
                        ),
                    },
                    "type": {
                        "type": "string",
                        "enum": list(TEXT_TYPES),
                        "default": "dialogue",
                    },
                    "style": {"$ref": "#/$defs/style"},
                    "review": {"type": "boolean", "default": False},
                },
                "allOf": [
                    {
                        "if": {
                            "properties": {"name": {"const": "UNKNOWN"}},
                            "required": ["name"],
                        },
                        "then": {
                            "properties": {"review": {"const": True}},
                            "required": ["review"],
                        },
                    },
                    {
                        "if": {
                            "properties": {"review": {"const": True}},
                            "required": ["review"],
                        },
                        "then": {"properties": {"name": {"const": "UNKNOWN"}}},
                    },
                ],
            },
        },
    }


def render_annotation_schema() -> str:
    body = yaml.safe_dump(
        annotation_json_schema(),
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    )
    return _GENERATED_HEADER + body


def write_annotation_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_annotation_schema(), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the annotation JSON Schema YAML")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/annotation.schema.yaml"),
        help="output path (default: docs/annotation.schema.yaml)",
    )
    arguments = parser.parse_args()
    write_annotation_schema(arguments.output)
    print(arguments.output)


if __name__ == "__main__":
    main()
