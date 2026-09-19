"""Canonical, provider-neutral annotation vocabulary.

This module is the only hand-maintained source of truth for annotation names,
text types, modes, and reading styles.  Validators, agent context, schema
code-generation, and the renderer all consume these values directly.
"""

from __future__ import annotations

from typing import Final

DEFAULT_ANNOTATION_MODE: Final = "dialogue"

ANNOTATION_MODES: Final = {
    "dialogue": {
        "description": "Allow narration and spoken dialogue. This is the default mode.",
        "text_types": ("narration", "dialogue"),
    },
    "thought": {
        "description": "Also allow explicitly represented internal speech as thought.",
        "text_types": ("narration", "dialogue", "thought"),
    },
}

TEXT_TYPES: Final = {
    "narration": "Narrator exposition, action, description, or attribution.",
    "dialogue": "Words spoken aloud. This is the default type of an explicit segment.",
    "thought": "Explicitly represented internal words; available only in thought mode.",
}

SYSTEM_NAMES: Final = {
    "NARRATOR": {
        "description": "Default speaker for narration and every uncovered processed line.",
    },
    "UNKNOWN": {
        "description": "Speaker cannot be resolved reliably and requires human review.",
    },
    "EXTRA": {
        "description": "Resolved incidental speaker without a reliable gender classification.",
    },
    "EXTRA_MALE": {
        "description": "Resolved incidental male speaker supported by the text or context.",
    },
    "EXTRA_FEMALE": {
        "description": "Resolved incidental female speaker supported by the text or context.",
    },
}

NARRATOR_NAME: Final = "NARRATOR"
UNKNOWN_NAME: Final = "UNKNOWN"
EXTRA_NAMES: Final = ("EXTRA", "EXTRA_MALE", "EXTRA_FEMALE")

STYLE_SCHEMA: Final = {
    "direction": {
        "description": (
            "Optional provider-neutral natural-language performance direction for the whole "
            "semantic segment."
        ),
        "kind": "direction",
    },
    "tags_before": {
        "description": (
            "Ordered provider-neutral free-text performance tags applied at the start of the "
            "semantic segment."
        ),
        "kind": "tags",
    },
    "tags_after": {
        "description": (
            "Ordered provider-neutral free-text performance tags applied at the end of the "
            "semantic segment."
        ),
        "kind": "tags",
    },
}

STYLE_FIELDS: Final = tuple(STYLE_SCHEMA)
STYLE_TAG_FIELDS: Final = tuple(
    field for field, spec in STYLE_SCHEMA.items() if spec["kind"] == "tags"
)


def allowed_text_types(mode: str) -> tuple[str, ...]:
    """Return text types enabled by an annotation mode."""
    try:
        return ANNOTATION_MODES[mode]["text_types"]
    except KeyError as error:
        allowed = ", ".join(ANNOTATION_MODES)
        raise ValueError(f"invalid annotation mode {mode!r}; allowed values: {allowed}") from error
