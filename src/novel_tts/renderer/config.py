from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .capabilities import get_capabilities
from .models import (
    AssemblyConfig,
    ExecutionConfig,
    OutputConfig,
    RenderConfig,
    RenderProfile,
    ReviewPolicy,
    StreamingMode,
    TimelineConfig,
    VoiceMode,
    VoiceSource,
    VoiceSpec,
    VoiceUsage,
)

VOICE_ALLOWED_FIELDS = {
    VoiceMode.PRESET: {"profile", "kind", "voice"},
    VoiceMode.SAVED_REFERENCE: {"profile", "kind", "reference_id"},
    VoiceMode.INLINE_CLONE: {
        "profile",
        "kind",
        "reference_audio",
        "reference_text",
    },
    VoiceMode.TEXT_DESIGN: {"profile", "kind", "description"},
}


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
        {"profiles", "output", "assembly", "execution", "review", "timeline"},
        "render config",
    )
    raw_profiles = _mapping(data.get("profiles"), "profiles")
    profiles: dict[str, RenderProfile] = {}
    for profile_id, raw in raw_profiles.items():
        item = _mapping(raw, f"profile {profile_id}")
        _reject_extra(
            item,
            {
                "provider",
                "model",
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
        api_key_env = item.get("api_key_env")
        if not all(isinstance(value, str) and value for value in (provider, model)):
            raise ValueError(f"profile {profile_id} requires provider and model")
        if not isinstance(api_key_env, str) or not api_key_env:
            raise ValueError(f"profile {profile_id} requires api_key_env")
        capability = get_capabilities(provider, model)
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
        profiles[profile_id] = RenderProfile(
            id=profile_id,
            provider=provider,
            model=model,
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

    output = _parse_output(_mapping(data.get("output", {}), "output"))
    assembly = _parse_assembly(_mapping(data.get("assembly", {}), "assembly"))
    execution = _parse_execution(_mapping(data.get("execution", {}), "execution"))
    review = _parse_review(_mapping(data.get("review", {}), "review"))
    timeline = _parse_timeline(_mapping(data.get("timeline", {}), "timeline"))
    return RenderConfig(
        root=render_root,
        profiles=profiles,
        output=output,
        assembly=assembly,
        execution=execution,
        review=review,
        timeline=timeline,
    )


def load_voice_catalog(
    render_root: Path, profiles: dict[str, RenderProfile]
) -> dict[str, dict[str, VoiceSource]]:
    path = render_root / "voices.yaml"
    data = _mapping(_load_yaml(path), f"voice catalog {path}")
    _reject_extra(data, {"voices"}, f"voice catalog {path}")
    raw_voices = _mapping(data.get("voices"), "voices")
    catalog: dict[str, dict[str, VoiceSource]] = {}
    for name, raw_sources in raw_voices.items():
        sources = _mapping(raw_sources, f"voice sources for {name}")
        parsed_sources: dict[str, VoiceSource] = {}
        for source_id, raw in sources.items():
            item = _mapping(raw, f"voice {name}.{source_id}")
            profile_id = item.get("profile")
            if not isinstance(profile_id, str) or profile_id not in profiles:
                raise ValueError(
                    f"voice {name}.{source_id} references missing profile {profile_id!r}"
                )
            kind_raw = item.get("kind")
            try:
                kind = VoiceMode(kind_raw)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"voice {name}.{source_id} has invalid kind {kind_raw!r}"
                ) from error
            _reject_extra(item, VOICE_ALLOWED_FIELDS[kind], f"voice {name}.{source_id}")
            spec = VoiceSpec(
                kind=kind,
                voice=item.get("voice"),
                reference_id=item.get("reference_id"),
                reference_audio=(
                    (path.parent / item["reference_audio"]).resolve()
                    if isinstance(item.get("reference_audio"), str)
                    else None
                ),
                reference_text=item.get("reference_text"),
                description=item.get("description"),
            )
            _validate_voice_spec(name, spec)
            validate_voice_for_profile(name, spec, profiles[profile_id])
            parsed_sources[source_id] = VoiceSource(source_id, profile_id, spec)
        catalog[name] = parsed_sources
    return catalog


def load_voice_usage(
    render_root: Path,
    catalog: dict[str, dict[str, VoiceSource]],
    profiles: dict[str, RenderProfile],
) -> VoiceUsage:
    path = render_root / "voice_used.yaml"
    data = _mapping(_load_yaml(path), f"voice usage {path}")
    _reject_extra(data, {"default_profile", "voices"}, f"voice usage {path}")
    default_profile = data.get("default_profile")
    if not isinstance(default_profile, str) or default_profile not in profiles:
        raise ValueError(f"voice_used default_profile {default_profile!r} does not exist")
    overrides = _mapping(data.get("voices", {}), "voice_used voices")
    for name, source_id in overrides.items():
        if name not in catalog:
            raise ValueError(f"voice_used references unknown person {name!r}")
        if not isinstance(source_id, str) or source_id not in catalog[name]:
            raise ValueError(f"voice_used for {name!r} references missing source {source_id!r}")
    return VoiceUsage(default_profile=default_profile, overrides=dict(overrides))


def resolve_voice_source(
    name: str,
    catalog: dict[str, dict[str, VoiceSource]],
    usage: VoiceUsage,
    forced_profile: str | None = None,
) -> VoiceSource:
    sources = catalog.get(name)
    if not sources:
        raise ValueError(f"no voices are configured for {name!r}")
    if forced_profile is None and name in usage.overrides:
        return sources[usage.overrides[name]]
    profile_id = forced_profile or usage.default_profile
    matches = [source for source in sources.values() if source.profile_id == profile_id]
    if not matches:
        raise ValueError(f"voice {name!r} has no source for profile {profile_id!r}")
    if len(matches) > 1:
        raise ValueError(f"voice {name!r} has multiple sources for profile {profile_id!r}")
    return matches[0]


def render_target(profile_id: str | None, usage: VoiceUsage) -> str:
    if profile_id is not None:
        return profile_id
    if not usage.overrides:
        return usage.default_profile
    selection = json.dumps(
        {
            "default_profile": usage.default_profile,
            "voices": usage.overrides,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(selection.encode()).hexdigest()[:10]
    return f"mixed-{digest}"


def validate_voice_for_profile(name: str, voice: VoiceSpec, profile: RenderProfile) -> None:
    capability = get_capabilities(profile.provider, profile.model)
    if voice.kind not in capability.voice_modes:
        supported = ", ".join(sorted(mode.value for mode in capability.voice_modes))
        raise ValueError(
            f"voice {name!r} uses {voice.kind}, but {profile.provider}/{profile.model} supports: "
            f"{supported}"
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
    defaults = OutputConfig()
    sample_format = data.get("sample_format", defaults.sample_format)
    final_format = data.get("final_format", defaults.final_format)
    if sample_format != "s16":
        raise ValueError("output.sample_format currently supports only s16")
    if final_format not in {"wav", "mp3", "opus", "m4a"}:
        raise ValueError("output.final_format must be wav, mp3, opus, or m4a")
    return OutputConfig(
        sample_rate=_positive_int(
            data.get("sample_rate", defaults.sample_rate), "output.sample_rate"
        ),
        channels=_positive_int(data.get("channels", defaults.channels), "output.channels"),
        sample_format=sample_format,
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
        name: _nonnegative_int(data.get(name, getattr(defaults, name)), f"assembly.{name}")
        for name in fields
    }
    return AssemblyConfig(**values)


def _parse_execution(data: dict[str, Any]) -> ExecutionConfig:
    fields = {"max_chars_per_request", "manifest_flush_interval_seconds"}
    _reject_extra(data, fields, "execution")
    defaults = ExecutionConfig()
    return ExecutionConfig(
        max_chars_per_request=_positive_int(
            data.get("max_chars_per_request", defaults.max_chars_per_request),
            "execution.max_chars_per_request",
        ),
        manifest_flush_interval_seconds=_nonnegative_number(
            data.get(
                "manifest_flush_interval_seconds",
                defaults.manifest_flush_interval_seconds,
            ),
            "execution.manifest_flush_interval_seconds",
        ),
    )


def _parse_review(data: dict[str, Any]) -> ReviewPolicy:
    _reject_extra(data, {"fail_on_review", "fail_on_unknown"}, "review")
    defaults = ReviewPolicy()
    return ReviewPolicy(
        fail_on_review=_boolean(
            data.get("fail_on_review", defaults.fail_on_review), "review.fail_on_review"
        ),
        fail_on_unknown=_boolean(
            data.get("fail_on_unknown", defaults.fail_on_unknown), "review.fail_on_unknown"
        ),
    )


def _parse_timeline(data: dict[str, Any]) -> TimelineConfig:
    _reject_extra(data, {"enabled", "include_silence_events", "subtitles"}, "timeline")
    defaults = TimelineConfig()
    subtitles = _mapping(data.get("subtitles", {}), "timeline.subtitles")
    _reject_extra(
        subtitles,
        {"formats", "show_speaker", "include_narration"},
        "timeline.subtitles",
    )
    raw_formats = subtitles.get("formats", list(defaults.subtitle_formats))
    if not isinstance(raw_formats, list) or any(
        not isinstance(value, str) for value in raw_formats
    ):
        raise ValueError("timeline.subtitles.formats must be a list of strings")
    formats = tuple(raw_formats)
    unsupported = set(formats) - {"srt", "vtt"}
    if unsupported:
        raise ValueError(
            "timeline.subtitles.formats has unsupported values: " + ", ".join(sorted(unsupported))
        )
    return TimelineConfig(
        enabled=_boolean(data.get("enabled", defaults.enabled), "timeline.enabled"),
        include_silence_events=_boolean(
            data.get("include_silence_events", defaults.include_silence_events),
            "timeline.include_silence_events",
        ),
        subtitle_formats=formats,
        show_speaker=_boolean(
            subtitles.get("show_speaker", defaults.show_speaker),
            "timeline.subtitles.show_speaker",
        ),
        include_narration=_boolean(
            subtitles.get("include_narration", defaults.include_narration),
            "timeline.subtitles.include_narration",
        ),
    )


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


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


def _nonnegative_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{label} must be a non-negative number")
    return float(value)
