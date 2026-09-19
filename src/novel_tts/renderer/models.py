from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Voice:
    id: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutputConfig:
    sample_rate: int = 24000
    channels: int = 1
    final_format: str = "mp3"


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


@dataclass(frozen=True)
class RenderConfig:
    root: Path
    endpoint: str
    model: str
    api_key_env: str
    concurrency: int = 2
    timeout_seconds: float = 120
    retries: int = 2
    output: OutputConfig = field(default_factory=OutputConfig)
    assembly: AssemblyConfig = field(default_factory=AssemblyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)


@dataclass(frozen=True)
class CompiledStyle:
    values: dict[str, Any] | None = None


@dataclass(frozen=True)
class RenderJob:
    id: str
    chapter: str
    line_start: int
    line_end: int
    text: str
    name: str
    text_type: str
    style: dict[str, str] | None
    voice: Voice
    chunk_index: int
    chunk_count: int
    cache_key: str
    compiled_style: CompiledStyle = field(default_factory=CompiledStyle)
    scene_id: str | None = None


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
class AudioResult:
    audio: bytes
    audio_format: str = "wav"
    request_id: str | None = None
    attempts: int = 1
    elapsed_ms: int = 0
