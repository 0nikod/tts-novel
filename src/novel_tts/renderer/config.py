from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ..annotation_schema import UNKNOWN_NAME
from .models import (
    AssemblyConfig,
    ExecutionConfig,
    OutputConfig,
    RenderConfig,
    RenderProfile,
    Voice,
)
from .providers import get_provider

_TARGET_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError(f"configuration file does not exist: {path}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML in {path}: {error}") from error


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} keys must be strings")
    return value


def _reject_extra(data: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise ValueError(f"{label} has unsupported fields: {', '.join(sorted(extra))}")


def load_render_config(book_root: Path) -> RenderConfig:
    render_root = book_root / "render"
    path = render_root / "config.yaml"
    data = _mapping(_load_yaml(path), "render config")
    _reject_extra(
        data,
        {
            "target",
            "default_profile",
            "profiles",
            "output",
            "assembly",
            "execution",
        },
        "render config",
    )

    target = data.get("target")
    if not isinstance(target, str) or not _TARGET_PATTERN.fullmatch(target):
        raise ValueError(
            "render config target must start with an ASCII letter or digit and contain only "
            "letters, digits, '.', '_', or '-'"
        )

    raw_profiles = _mapping(data.get("profiles"), "profiles")
    if not raw_profiles:
        raise ValueError("render config profiles must not be empty")
    profiles: dict[str, RenderProfile] = {}
    for profile_id, raw_profile in raw_profiles.items():
        if not profile_id.strip():
            raise ValueError("profile IDs must be non-empty strings")
        item = _mapping(raw_profile, f"profile {profile_id}")
        _reject_extra(
            item,
            {
                "provider",
                "endpoint",
                "model",
                "api_key_env",
                "request",
                "concurrency",
                "timeout_seconds",
                "retries",
            },
            f"profile {profile_id}",
        )
        provider_id = item.get("provider")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError(f"profile {profile_id} provider must be a non-empty string")
        try:
            adapter = get_provider(provider_id)
        except ValueError as error:
            raise ValueError(f"profile {profile_id}: {error}") from error

        endpoint = item.get("endpoint", adapter.default_endpoint)
        model = item.get("model")
        api_key_env = item.get("api_key_env")
        for field, value in (
            ("endpoint", endpoint),
            ("model", model),
            ("api_key_env", api_key_env),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"profile {profile_id} {field} must be a non-empty string")

        profile = RenderProfile(
            id=profile_id,
            provider=provider_id,
            endpoint=endpoint,
            model=model,
            api_key_env=api_key_env,
            request=dict(_mapping(item.get("request", {}), f"profile {profile_id}.request")),
            concurrency=_positive_int(
                item.get("concurrency", 1), f"profile {profile_id}.concurrency"
            ),
            timeout_seconds=_positive_number(
                item.get("timeout_seconds", 120), f"profile {profile_id}.timeout_seconds"
            ),
            retries=_nonnegative_int(item.get("retries", 2), f"profile {profile_id}.retries"),
        )
        errors = adapter.validate_profile(profile)
        if errors:
            raise ValueError(f"profile {profile_id}: {'; '.join(errors)}")
        profiles[profile_id] = profile

    default_profile = data.get("default_profile")
    if not isinstance(default_profile, str) or default_profile not in profiles:
        raise ValueError(
            f"render config default_profile {default_profile!r} does not reference a profile"
        )

    return RenderConfig(
        root=render_root,
        target=target,
        default_profile=default_profile,
        profiles=profiles,
        output=_parse_output(_mapping(data.get("output", {}), "output")),
        assembly=_parse_assembly(_mapping(data.get("assembly", {}), "assembly")),
        execution=_parse_execution(_mapping(data.get("execution", {}), "execution")),
    )


def load_voice_catalog(render_root: Path, config: RenderConfig) -> dict[str, Voice]:
    path = render_root / "voices.yaml"
    data = _mapping(_load_yaml(path), f"voice catalog {path}")
    _reject_extra(data, {"voices"}, f"voice catalog {path}")
    raw_voices = _mapping(data.get("voices"), "voices")
    catalog: dict[str, Voice] = {}

    for voice_id, raw_voice in raw_voices.items():
        if not voice_id.strip():
            raise ValueError("voice IDs must be non-empty strings")
        item = dict(_mapping(raw_voice, f"voice {voice_id}"))
        profile_id = item.pop("profile", config.default_profile)
        if not isinstance(profile_id, str) or profile_id not in config.profiles:
            raise ValueError(
                f"voice {voice_id!r} profile {profile_id!r} does not reference a profile"
            )
        if not item:
            raise ValueError(f"voice {voice_id!r} has no provider parameters")
        catalog[voice_id] = Voice(
            id=voice_id,
            profile_id=profile_id,
            parameters=item,
        )
    return catalog


def load_voice_usage(render_root: Path, catalog: dict[str, Voice]) -> dict[str, str]:
    path = render_root / "voice_used.yaml"
    data = _mapping(_load_yaml(path), f"voice usage {path}")
    _reject_extra(data, {"voices"}, f"voice usage {path}")
    usage = _mapping(data.get("voices"), "voice_used voices")
    result: dict[str, str] = {}
    for name, voice_id in usage.items():
        if name == UNKNOWN_NAME:
            raise ValueError("UNKNOWN must not appear in voice_used.yaml")
        if not isinstance(voice_id, str) or voice_id not in catalog:
            raise ValueError(f"voice_used for {name!r} references missing voice {voice_id!r}")
        result[name] = voice_id
    return result


def resolve_voice(name: str, catalog: dict[str, Voice], usage: dict[str, str]) -> Voice:
    voice_id = usage.get(name)
    if voice_id is None:
        raise ValueError(f"no voice selected for {name!r}")
    try:
        return catalog[voice_id]
    except KeyError as error:
        raise ValueError(f"voice {voice_id!r} selected for {name!r} does not exist") from error


def render_target(config: RenderConfig) -> str:
    return config.target


def _parse_output(data: dict[str, Any]) -> OutputConfig:
    _reject_extra(data, {"sample_rate", "channels", "final_format"}, "output")
    final_format = data.get("final_format", "mp3")
    if final_format not in {"wav", "mp3", "opus", "m4a"}:
        raise ValueError("output.final_format must be wav, mp3, opus, or m4a")
    return OutputConfig(
        sample_rate=_positive_int(data.get("sample_rate", 24000), "output.sample_rate"),
        channels=_positive_int(data.get("channels", 1), "output.channels"),
        final_format=final_format,
    )


def _parse_assembly(data: dict[str, Any]) -> AssemblyConfig:
    fields = {
        "chunk_gap_ms",
        "dialogue_gap_ms",
        "narration_gap_ms",
        "scene_gap_ms",
        "chapter_gap_ms",
    }
    _reject_extra(data, fields, "assembly")
    defaults = AssemblyConfig()
    values = {
        field: _nonnegative_int(data.get(field, getattr(defaults, field)), f"assembly.{field}")
        for field in fields
    }
    return AssemblyConfig(**values)


def _parse_execution(data: dict[str, Any]) -> ExecutionConfig:
    _reject_extra(data, {"max_chars_per_request"}, "execution")
    return ExecutionConfig(
        max_chars_per_request=_positive_int(
            data.get("max_chars_per_request", 200), "execution.max_chars_per_request"
        )
    )


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{label} must be a positive number")
    return float(value)
