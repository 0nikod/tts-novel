from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class VoiceMode(StrEnum):
    PRESET = "preset"
    SAVED_REFERENCE = "saved_reference"
    INLINE_CLONE = "inline_clone"
    TEXT_DESIGN = "text_design"


class StreamingMode(StrEnum):
    NONE = "none"
    REALTIME = "realtime"
    BUFFERED = "buffered"


@dataclass(frozen=True)
class ModelCapabilities:
    provider: str
    model: str
    voice_modes: frozenset[VoiceMode]
    streaming_modes: frozenset[StreamingMode]
    output_formats: frozenset[str]
    style_controls: frozenset[str]
    supports_multi_speaker: bool = False
    supports_timestamps: bool = False
    reference_audio_formats: frozenset[str] = frozenset()
    max_reference_audio_bytes: int | None = None


@dataclass(frozen=True)
class VoiceSpec:
    kind: VoiceMode
    voice: str | None = None
    reference_id: str | None = None
    reference_audio: Path | None = None
    reference_text: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class RenderProfile:
    id: str
    provider: str
    model: str
    api_key_env: str
    request: dict[str, Any]
    concurrency: int = 1
    timeout_seconds: float = 120
    retries: int = 4
    unsupported_style: str = "error"


@dataclass(frozen=True)
class OutputConfig:
    sample_rate: int = 24000
    channels: int = 1
    sample_format: str = "s16"
    final_format: str = "wav"


@dataclass(frozen=True)
class AssemblyConfig:
    chunk_gap_ms: int = 0
    dialogue_gap_ms: int = 180
    narration_gap_ms: int = 260
    scene_gap_ms: int = 800
    chapter_gap_ms: int = 1500


@dataclass(frozen=True)
class ExecutionConfig:
    max_chars_per_request: int = 200
    manifest_flush_interval_seconds: float = 1.0


@dataclass(frozen=True)
class ReviewPolicy:
    fail_on_review: bool = True
    fail_on_unknown: bool = True


@dataclass(frozen=True)
class TimelineConfig:
    enabled: bool = True
    include_silence_events: bool = True
    subtitle_formats: tuple[str, ...] = ("srt", "vtt")
    show_speaker: bool = True
    include_narration: bool = True


@dataclass(frozen=True)
class RenderConfig:
    root: Path
    profiles: dict[str, RenderProfile]
    output: OutputConfig = field(default_factory=OutputConfig)
    assembly: AssemblyConfig = field(default_factory=AssemblyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    review: ReviewPolicy = field(default_factory=ReviewPolicy)
    timeline: TimelineConfig = field(default_factory=TimelineConfig)


@dataclass(frozen=True)
class VoiceSource:
    id: str
    profile_id: str
    voice: VoiceSpec


@dataclass(frozen=True)
class VoiceUsage:
    default_profile: str
    overrides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CompiledStyle:
    text: str
    instruction: str | None = None
    request_overrides: dict[str, Any] = field(default_factory=dict)
    unsupported_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderJob:
    id: str
    chapter: str
    line_start: int
    line_end: int
    scene_id: str
    name: str
    text_type: str
    source_text: str
    style: dict[str, str | None] | None
    review: bool
    review_reason: str | None
    profile: RenderProfile
    voice: VoiceSpec
    voice_source: str
    chunk_index: int
    chunk_count: int
    compiled: CompiledStyle
    cache_key: str
    legacy_cache_key: str | None = None


@dataclass(frozen=True)
class RenderIssue:
    severity: str
    message: str
    job_id: str | None = None

    def __str__(self) -> str:
        prefix = f"[{self.job_id}] " if self.job_id else ""
        return f"{self.severity} {prefix}{self.message}"


@dataclass
class RenderPlan:
    jobs: list[RenderJob] = field(default_factory=list)
    issues: list[RenderIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[RenderIssue]:
        return [issue for issue in self.issues if issue.severity == "ERROR"]


@dataclass(frozen=True)
class PreparedRequest:
    url: str
    headers: dict[str, str]
    json_body: dict[str, Any] | None = None
    content: bytes | None = None
    response_kind: str = "raw"
    audio_format: str = "wav"


@dataclass(frozen=True)
class ProviderResult:
    audio: bytes
    audio_format: str
    request_id: str | None = None
