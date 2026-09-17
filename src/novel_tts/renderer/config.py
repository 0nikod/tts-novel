from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .capabilities import get_capabilities
from .models import (
    AssemblyConfig,
    OutputConfig,
    RenderConfig,
    RenderProfile,
    ReviewPolicy,
    StreamingMode,
    VoiceMode,
    VoiceSpec,
)


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
        {"default_profile", "profiles", "routing", "output", "assembly", "review"},
        "render config",
    )
    default_profile = data.get("default_profile")
    if not isinstance(default_profile, str) or not default_profile:
        raise ValueError("render config requires a non-empty default_profile")

    raw_profiles = _mapping(data.get("profiles"), "profiles")
    profiles: dict[str, RenderProfile] = {}
    for profile_id, raw in raw_profiles.items():
        item = _mapping(raw, f"profile {profile_id}")
        _reject_extra(
            item,
            {
                "provider",
                "model",
                "voice_mode",
                "voice_file",
                "api_key_env",
                "request",
                "concurrency",
                "timeout_seconds",
                "retries",
                "style_policy",
            },
            f"profile {profile_id}",
        )
        provider = item.get("provider")
        model = item.get("model")
        voice_mode_raw = item.get("voice_mode")
        voice_file_raw = item.get("voice_file")
        api_key_env = item.get("api_key_env")
        if not all(isinstance(value, str) and value for value in (provider, model, voice_mode_raw)):
            raise ValueError(f"profile {profile_id} requires provider, model, and voice_mode")
        if not isinstance(voice_file_raw, str) or not voice_file_raw:
            raise ValueError(f"profile {profile_id} requires voice_file")
        if not isinstance(api_key_env, str) or not api_key_env:
            raise ValueError(f"profile {profile_id} requires api_key_env")
        try:
            voice_mode = VoiceMode(voice_mode_raw)
        except ValueError as error:
            raise ValueError(
                f"profile {profile_id} has invalid voice_mode {voice_mode_raw!r}"
            ) from error
        capability = get_capabilities(provider, model)
        if voice_mode not in capability.voice_modes:
            supported = ", ".join(sorted(mode.value for mode in capability.voice_modes))
            raise ValueError(
                f"profile {profile_id}: {provider}/{model} does not support {voice_mode}; "
                f"supported voice modes: {supported}"
            )
        request = _mapping(item.get("request", {}), f"profile {profile_id}.request")
        stream = request.get("stream", False)
        if not isinstance(stream, bool):
            raise ValueError(f"profile {profile_id}.request.stream must be boolean")
        streaming_mode = _streaming_mode(provider, model, stream)
        if streaming_mode not in capability.streaming_modes:
            supported = ", ".join(sorted(mode.value for mode in capability.streaming_modes))
            raise ValueError(
                f"profile {profile_id}: streaming mode {streaming_mode} is unsupported; "
                f"supported modes: {supported}"
            )
        audio_format = request.get("format", "wav")
        if not isinstance(audio_format, str):
            raise ValueError(f"profile {profile_id}.request.format must be a string")
        if audio_format not in capability.output_formats:
            supported = ", ".join(sorted(capability.output_formats))
            raise ValueError(
                f"profile {profile_id}: format {audio_format!r} is unsupported; "
                f"supported formats: {supported}"
            )
        style_policy = _mapping(item.get("style_policy", {}), f"profile {profile_id}.style_policy")
        unsupported_style = style_policy.get("unsupported", "error")
        if unsupported_style not in {"error", "warn_and_omit"}:
            raise ValueError(
                f"profile {profile_id}.style_policy.unsupported must be error or warn_and_omit"
            )
        profile = RenderProfile(
            id=profile_id,
            provider=provider,
            model=model,
            voice_mode=voice_mode,
            voice_file=(render_root / voice_file_raw).resolve(),
            api_key_env=api_key_env,
            request=dict(request),
            concurrency=_positive_int(
                item.get("concurrency", 1), f"profile {profile_id}.concurrency"
            ),
            timeout_seconds=_positive_number(
                item.get("timeout_seconds", 120), f"profile {profile_id}.timeout_seconds"
            ),
            retries=_nonnegative_int(item.get("retries", 4), f"profile {profile_id}.retries"),
            unsupported_style=unsupported_style,
        )
        profiles[profile_id] = profile
    if default_profile not in profiles:
        raise ValueError(f"default profile {default_profile!r} does not exist")

    routing = _mapping(data.get("routing", {}), "routing")
    _reject_extra(routing, {"persons"}, "routing")
    person_routes = _mapping(routing.get("persons", {}), "routing.persons")
    for name, profile_id in person_routes.items():
        if not isinstance(profile_id, str) or profile_id not in profiles:
            raise ValueError(f"routing for {name!r} references missing profile {profile_id!r}")

    output = _parse_output(_mapping(data.get("output", {}), "output"))
    assembly = _parse_assembly(_mapping(data.get("assembly", {}), "assembly"))
    review = _parse_review(_mapping(data.get("review", {}), "review"))
    return RenderConfig(
        root=render_root,
        default_profile=default_profile,
        profiles=profiles,
        person_routes=dict(person_routes),
        output=output,
        assembly=assembly,
        review=review,
    )


def load_voice_file(profile: RenderProfile) -> dict[str, VoiceSpec]:
    data = _mapping(_load_yaml(profile.voice_file), f"voice file {profile.voice_file}")
    voices: dict[str, VoiceSpec] = {}
    for name, raw in data.items():
        item = _mapping(raw, f"voice {name}")
        kind_raw = item.get("kind", profile.voice_mode.value)
        try:
            kind = VoiceMode(kind_raw)
        except (TypeError, ValueError) as error:
            raise ValueError(f"voice {name!r} has invalid kind {kind_raw!r}") from error
        allowed = {
            VoiceMode.PRESET: {"kind", "voice"},
            VoiceMode.SAVED_REFERENCE: {"kind", "reference_id"},
            VoiceMode.INLINE_CLONE: {"kind", "reference_audio", "reference_text"},
            VoiceMode.TEXT_DESIGN: {"kind", "description"},
        }[kind]
        _reject_extra(item, allowed, f"voice {name}")
        spec = VoiceSpec(
            kind=kind,
            voice=item.get("voice"),
            reference_id=item.get("reference_id"),
            reference_audio=(
                (profile.voice_file.parent / item["reference_audio"]).resolve()
                if isinstance(item.get("reference_audio"), str)
                else None
            ),
            reference_text=item.get("reference_text"),
            description=item.get("description"),
        )
        _validate_voice_spec(name, spec)
        voices[name] = spec
    return voices


def validate_voice_for_profile(name: str, voice: VoiceSpec, profile: RenderProfile) -> None:
    capability = get_capabilities(profile.provider, profile.model)
    if voice.kind not in capability.voice_modes:
        supported = ", ".join(sorted(mode.value for mode in capability.voice_modes))
        raise ValueError(
            f"voice {name!r} uses {voice.kind}, but {profile.provider}/{profile.model} supports: "
            f"{supported}"
        )
    if voice.kind != profile.voice_mode:
        raise ValueError(
            f"voice {name!r} uses {voice.kind}, but profile {profile.id} requires "
            f"{profile.voice_mode}"
        )
    if voice.reference_audio is not None:
        suffix = voice.reference_audio.suffix.lower().lstrip(".")
        if suffix not in capability.reference_audio_formats:
            supported = ", ".join(sorted(capability.reference_audio_formats))
            raise ValueError(
                f"voice {name!r} reference format {suffix!r} is unsupported; "
                f"supported formats: {supported}"
            )
        if not voice.reference_audio.is_file():
            raise ValueError(
                f"voice {name!r} reference audio does not exist: {voice.reference_audio}"
            )
        size = voice.reference_audio.stat().st_size
        if capability.max_reference_audio_bytes is not None:
            # Base64 expands data by roughly 4/3. MiMo's documented limit applies post-encoding.
            encoded_size = ((size + 2) // 3) * 4
            if encoded_size > capability.max_reference_audio_bytes:
                raise ValueError(f"voice {name!r} reference audio exceeds the encoded size limit")
    if (
        profile.provider == "fish_audio"
        and voice.kind == VoiceMode.INLINE_CLONE
        and not voice.reference_text
    ):
        raise ValueError(f"voice {name!r} requires reference_text for Fish inline cloning")


def _validate_voice_spec(name: str, spec: VoiceSpec) -> None:
    if spec.kind == VoiceMode.INLINE_CLONE:
        if spec.reference_audio is None:
            raise ValueError(f"voice {name!r} requires reference_audio for kind {spec.kind}")
        if spec.reference_text is not None and not isinstance(spec.reference_text, str):
            raise ValueError(f"voice {name!r} reference_text must be a string")
        return
    required = {
        VoiceMode.PRESET: ("voice", spec.voice),
        VoiceMode.SAVED_REFERENCE: ("reference_id", spec.reference_id),
        VoiceMode.TEXT_DESIGN: ("description", spec.description),
    }
    field_name, value = required[spec.kind]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"voice {name!r} requires a non-empty string {field_name} for kind {spec.kind}"
        )


def _streaming_mode(provider: str, model: str, stream: bool) -> StreamingMode:
    if not stream:
        return StreamingMode.NONE
    if provider == "mimo" and model != "mimo-v2.5-tts":
        return StreamingMode.BUFFERED
    return StreamingMode.REALTIME


def _parse_output(data: dict[str, Any]) -> OutputConfig:
    _reject_extra(data, {"sample_rate", "channels", "sample_format", "final_format"}, "output")
    sample_format = data.get("sample_format", "s16")
    final_format = data.get("final_format", "wav")
    if sample_format != "s16":
        raise ValueError("output.sample_format currently supports only s16")
    if final_format not in {"wav", "mp3", "opus", "m4a"}:
        raise ValueError("output.final_format must be wav, mp3, opus, or m4a")
    return OutputConfig(
        sample_rate=_positive_int(data.get("sample_rate", 24000), "output.sample_rate"),
        channels=_positive_int(data.get("channels", 1), "output.channels"),
        sample_format=sample_format,
        final_format=final_format,
    )


def _parse_assembly(data: dict[str, Any]) -> AssemblyConfig:
    fields = {"dialogue_gap_ms", "narration_gap_ms", "scene_gap_ms", "chapter_gap_ms"}
    _reject_extra(data, fields, "assembly")
    values = {
        name: _nonnegative_int(data.get(name, default), f"assembly.{name}")
        for name, default in (
            ("dialogue_gap_ms", 180),
            ("narration_gap_ms", 260),
            ("scene_gap_ms", 800),
            ("chapter_gap_ms", 1500),
        )
    }
    return AssemblyConfig(**values)


def _parse_review(data: dict[str, Any]) -> ReviewPolicy:
    _reject_extra(data, {"fail_on_review", "fail_on_unknown"}, "review")
    values = {}
    for name in ("fail_on_review", "fail_on_unknown"):
        value = data.get(name, True)
        if not isinstance(value, bool):
            raise ValueError(f"review.{name} must be boolean")
        values[name] = value
    return ReviewPolicy(**values)


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
