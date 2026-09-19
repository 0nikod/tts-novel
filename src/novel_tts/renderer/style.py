from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ..annotation_schema import STYLE_VALUES
from .models import CompiledStyle, RenderProfile

FISH_TAGS: dict[str, dict[str, str]] = {
    "emotion": {
        "angry": "angry",
        "calm": "calm",
        "excited": "excited",
        "happy": "happy",
        "nervous": "nervous",
        "sad": "sad",
        "shocked": "surprised",
    },
    "delivery": {
        "scolding": "angry",
        "shout": "shouting",
        "whisper": "whispering",
    },
    "volume": {"high": "loud", "low": "soft tone"},
    "vocal_action_before": {
        "laugh": "laughing",
        "sigh": "sighing",
        "deep_breath": "deep breath",
    },
    "vocal_action_after": {
        "laugh": "laughing",
        "sigh": "sighing",
        "deep_breath": "deep breath",
    },
}
FISH_PACE = {"slow": 0.85, "fast": 1.15}
FISH_VOLUME = {"low": -3, "high": 3}

MIMO_TERMS: dict[str, dict[str, str]] = {
    "emotion": {
        "angry": "愤怒",
        "calm": "平静",
        "excited": "激动",
        "happy": "高兴",
        "nervous": "紧张",
        "sad": "悲伤",
        "shocked": "震惊",
    },
    "delivery": {
        "scolding": "斥责",
        "shout": "提高音量喊话",
        "whisper": "低声耳语",
    },
    "volume": {"high": "提高音量", "low": "降低音量"},
    "pace": {"fast": "加快语速", "slow": "放慢语速"},
}
MIMO_ACTIONS = {
    "laugh": "笑",
    "sigh": "叹气",
    "deep_breath": "深呼吸",
}


def validate_provider_default_mappings(
    provider: str, mappings: Mapping[str, Mapping[str, Any]]
) -> None:
    """Reject annotation keys in provider defaults that are outside the shared taxonomy."""
    for field, values in mappings.items():
        if field not in STYLE_VALUES:
            raise ValueError(f"{provider} default mappings contain unknown style field {field!r}")
        invalid = set(values) - set(STYLE_VALUES[field])
        if invalid:
            invalid_values = ", ".join(sorted(map(repr, invalid)))
            raise ValueError(
                f"{provider} default mappings for {field} contain values outside "
                f"STYLE_VALUES: {invalid_values}"
            )


validate_provider_default_mappings("fish_audio tags", FISH_TAGS)
validate_provider_default_mappings(
    "fish_audio controls", {"pace": FISH_PACE, "volume": FISH_VOLUME}
)
validate_provider_default_mappings("mimo terms", MIMO_TERMS)
validate_provider_default_mappings(
    "mimo actions",
    {"vocal_action_before": MIMO_ACTIONS, "vocal_action_after": MIMO_ACTIONS},
)


def validate_style_mappings(mappings: Mapping[Any, Any]) -> None:
    """Validate provider remaps without allowing them to extend annotation vocabulary."""
    allowed_providers = {"fish_audio", "mimo"}
    for provider, provider_mappings in mappings.items():
        if provider not in allowed_providers:
            raise ValueError(f"render/styles.yaml has unknown provider {provider!r}")
        if not isinstance(provider_mappings, dict):
            raise ValueError(f"render/styles.yaml {provider} must be a mapping")

        allowed_fields = set(STYLE_VALUES)
        if provider == "fish_audio":
            allowed_fields.add("volume_db")
        for field, values in provider_mappings.items():
            if field not in allowed_fields:
                raise ValueError(f"render/styles.yaml {provider} has unknown style field {field!r}")
            if not isinstance(values, dict):
                raise ValueError(f"render/styles.yaml {provider}.{field} must be a mapping")

            annotation_field = "volume" if field == "volume_db" else field
            canonical_values = STYLE_VALUES[annotation_field]
            for value, output in values.items():
                if value not in canonical_values:
                    allowed = ", ".join(canonical_values)
                    raise ValueError(
                        f"render/styles.yaml {provider}.{field} has non-canonical annotation "
                        f"value {value!r}; allowed values: {allowed}"
                    )
                numeric_output = provider == "fish_audio" and field in {"pace", "volume_db"}
                if numeric_output:
                    if (
                        not isinstance(output, (int, float))
                        or isinstance(output, bool)
                        or not math.isfinite(output)
                    ):
                        raise ValueError(
                            f"render/styles.yaml {provider}.{field}.{value} must be a finite number"
                        )
                elif not isinstance(output, str) or not output.strip():
                    raise ValueError(
                        f"render/styles.yaml {provider}.{field}.{value} must be a non-empty string"
                    )


def load_style_mappings(render_root: Path) -> dict[str, Any]:
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
    validate_style_mappings(data)
    return data


def compile_style(
    profile: RenderProfile,
    text: str,
    style: dict[str, str | None] | None,
    custom_mappings: dict[str, Any] | None = None,
) -> CompiledStyle:
    if not style or not any(value is not None for value in style.values()):
        return CompiledStyle(text=text)
    mappings = custom_mappings or {}
    if profile.provider == "fish_audio":
        return _compile_fish(text, style, mappings.get("fish_audio", {}))
    if profile.provider == "mimo":
        return _compile_mimo(text, style, mappings.get("mimo", {}))
    return CompiledStyle(text=text, unsupported_fields=tuple(sorted(style)))


def _compile_fish(text: str, style: dict[str, str | None], custom: Any) -> CompiledStyle:
    custom_map = custom if isinstance(custom, dict) else {}
    before: list[str] = []
    after: list[str] = []
    unsupported: list[str] = []
    overrides: dict[str, Any] = {}

    for field, value in style.items():
        if value is None:
            continue
        if field == "pace":
            speed = _mapped_value(custom_map, field, value, FISH_PACE)
            if isinstance(speed, (int, float)) and not isinstance(speed, bool):
                overrides.setdefault("prosody", {})["speed"] = float(speed)
            else:
                unsupported.append(f"{field}={value}")
            continue
        tag = _mapped_value(custom_map, field, value, FISH_TAGS.get(field, {}))
        if not isinstance(tag, str) or not tag:
            unsupported.append(f"{field}={value}")
            continue
        marker = f"[{tag}]"
        if field == "vocal_action_after":
            after.append(marker)
        else:
            before.append(marker)
        if field == "volume":
            volume = _mapped_value(custom_map, "volume_db", value, FISH_VOLUME)
            if isinstance(volume, (int, float)) and not isinstance(volume, bool):
                overrides.setdefault("prosody", {})["volume"] = float(volume)
    return CompiledStyle(
        text="".join(before) + text + "".join(after),
        request_overrides=overrides,
        unsupported_fields=tuple(unsupported),
    )


def _compile_mimo(text: str, style: dict[str, str | None], custom: Any) -> CompiledStyle:
    custom_map = custom if isinstance(custom, dict) else {}
    instructions: list[str] = []
    before: list[str] = []
    after: list[str] = []
    unsupported: list[str] = []
    for field, value in style.items():
        if value is None:
            continue
        if field in {"vocal_action_before", "vocal_action_after"}:
            action = _mapped_value(custom_map, field, value, MIMO_ACTIONS)
            if not isinstance(action, str) or not action:
                unsupported.append(f"{field}={value}")
                continue
            target = after if field == "vocal_action_after" else before
            target.append(f"（{action}）")
            continue
        term = _mapped_value(custom_map, field, value, MIMO_TERMS.get(field, {}))
        if not isinstance(term, str) or not term:
            unsupported.append(f"{field}={value}")
            continue
        instructions.append(term)
    instruction = "请使用" + "、".join(instructions) + "的方式朗读。" if instructions else None
    return CompiledStyle(
        text="".join(before) + text + "".join(after),
        instruction=instruction,
        unsupported_fields=tuple(unsupported),
    )


def _mapped_value(custom: dict[str, Any], field: str, value: str, defaults: Any) -> Any:
    custom_field = custom.get(field, {})
    if isinstance(custom_field, dict) and value in custom_field:
        return custom_field[value]
    if isinstance(defaults, dict):
        return defaults.get(value)
    return None
