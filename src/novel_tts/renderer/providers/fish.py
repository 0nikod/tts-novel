from __future__ import annotations

from copy import deepcopy
from typing import Any

import msgpack

from ..models import PreparedRequest, ProviderResult, RenderJob, VoiceMode
from .base import ProviderDriver

_ALLOWED_FIELDS = {
    "format",
    "sample_rate",
    "latency",
    "chunk_length",
    "normalize",
    "temperature",
    "top_p",
    "prosody",
    "mp3_bitrate",
    "opus_bitrate",
    "max_new_tokens",
    "repetition_penalty",
    "min_chunk_length",
    "condition_on_previous_chunks",
    "early_stop_threshold",
    "stream",
}


class FishAudioDriver(ProviderDriver):
    endpoint = "https://api.fish.audio/v1/tts"

    def validate_profile(self, job: RenderJob) -> None:
        request = job.profile.request
        extra = set(request) - _ALLOWED_FIELDS
        if extra:
            raise ValueError("unsupported Fish request fields: " + ", ".join(sorted(extra)))
        chunk_length = request.get("chunk_length", 300)
        if not isinstance(chunk_length, int) or isinstance(chunk_length, bool):
            raise ValueError("Fish chunk_length must be an integer")
        if not 100 <= chunk_length <= 300:
            raise ValueError("Fish chunk_length must be between 100 and 300")
        latency = request.get("latency", "normal")
        if latency not in {"normal", "balanced", "low"}:
            raise ValueError("Fish latency must be normal, balanced, or low")
        audio_format = request.get("format", "wav")
        if audio_format == "mp3" and request.get("mp3_bitrate", 128) not in {64, 128, 192}:
            raise ValueError("Fish mp3_bitrate must be 64, 128, or 192")

    def prepare(self, job: RenderJob, api_key: str) -> PreparedRequest:
        self.validate_profile(job)
        request_options = deepcopy(job.profile.request)
        request_options.pop("stream", None)
        payload: dict[str, Any] = {
            "text": job.compiled.text,
            **request_options,
        }
        for key, value in job.compiled.request_overrides.items():
            if key == "prosody":
                payload.setdefault("prosody", {}).update(value)
            else:
                payload[key] = value
        payload.setdefault("format", "wav")
        payload.setdefault("chunk_length", 300)
        if job.voice.kind == VoiceMode.SAVED_REFERENCE:
            payload["reference_id"] = job.voice.reference_id
            return PreparedRequest(
                url=self.endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "model": job.profile.model,
                },
                json_body=payload,
                response_kind="raw",
                audio_format=str(payload["format"]),
            )
        if job.voice.kind == VoiceMode.INLINE_CLONE:
            assert job.voice.reference_audio is not None
            payload["references"] = [
                {
                    "audio": job.voice.reference_audio.read_bytes(),
                    "text": job.voice.reference_text,
                }
            ]
            return PreparedRequest(
                url=self.endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/msgpack",
                    "model": job.profile.model,
                },
                content=msgpack.packb(payload, use_bin_type=True),
                response_kind="raw",
                audio_format=str(payload["format"]),
            )
        raise ValueError(f"Fish Audio does not support voice kind {job.voice.kind}")

    def decode(self, request: PreparedRequest, body: bytes) -> ProviderResult:
        if not body:
            raise ValueError("Fish Audio returned empty audio")
        return ProviderResult(audio=body, audio_format=request.audio_format)
