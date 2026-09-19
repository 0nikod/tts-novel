from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
from typing import Any

from novel_tts.renderer.http import TTSRequestError
from novel_tts.renderer.models import (
    AudioResult,
    CompiledStyle,
    HttpResult,
    PreparedRequest,
    RenderProfile,
    Voice,
)
from novel_tts.renderer.providers.base import ProviderAdapter

_CONTENT_FORMATS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/mp4": "m4a",
    "application/octet-stream": "wav",
}


class CustomProvider(ProviderAdapter):
    id = "custom"

    def validate_profile(self, profile: RenderProfile) -> list[str]:
        errors: list[str] = []
        allowed = {"audio_format", "response_kind", "parameters"}
        unknown = sorted(set(profile.request) - allowed)
        if unknown:
            errors.append(f"custom request has unknown keys: {', '.join(unknown)}")
        response_kind = profile.request.get("response_kind", "auto")
        if response_kind not in {"auto", "audio", "json"}:
            errors.append("custom request.response_kind must be auto, audio, or json")
        audio_format = profile.request.get("audio_format", "wav")
        if not isinstance(audio_format, str) or not audio_format.strip():
            errors.append("custom request.audio_format must be a non-empty string")
        parameters = profile.request.get("parameters", {})
        if not isinstance(parameters, dict):
            errors.append("custom request.parameters must be a mapping")
        return errors

    def validate_voice(self, render_root: Path, profile: RenderProfile, voice: Voice) -> list[str]:
        del render_root, profile
        return [] if voice.parameters else [f"voice {voice.id!r} has no custom parameters"]

    def prepare_request(
        self,
        render_root: Path,
        profile: RenderProfile,
        *,
        text: str,
        voice: Voice,
        style: CompiledStyle,
        api_key: str | None,
    ) -> PreparedRequest:
        del render_root
        if not api_key:
            raise TTSRequestError(
                f"environment variable {profile.api_key_env!r} is not set for custom TTS",
                attempts=0,
                elapsed_ms=0,
            )
        headers = {
            "Content-Type": "application/json",
            "Accept": "audio/*, application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload: dict[str, Any] = {
            "model": profile.model,
            "text": style.text or text,
            "voice": {**voice.parameters, "id": voice.id},
            "style": style.values or {},
        }
        parameters = profile.request.get("parameters")
        if parameters:
            payload["parameters"] = parameters

        return PreparedRequest(
            url=profile.endpoint,
            headers=headers,
            json_body=payload,
            response_kind=str(profile.request.get("response_kind", "auto")),
            audio_format=str(profile.request.get("audio_format", "wav")),
        )

    def decode_response(self, request: PreparedRequest, response: HttpResult) -> AudioResult:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        expects_json = request.response_kind == "json" or (
            request.response_kind == "auto" and not _is_audio_content_type(content_type)
        )
        if expects_json:
            audio, audio_format = _decode_json(response.body, request.audio_format)
        else:
            audio = response.body
            audio_format = _format_from_content_type(content_type, request.audio_format)

        if not audio:
            raise RuntimeError("custom TTS response contained no audio")
        return AudioResult(
            audio=audio,
            audio_format=audio_format,
            request_id=response.request_id,
            attempts=response.attempts,
            elapsed_ms=response.elapsed_ms,
        )


def _decode_json(body: bytes, default_format: str) -> tuple[bytes, str]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("custom TTS returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("custom TTS JSON response must be an object")

    encoded = payload.get("audio_base64", payload.get("audio"))
    if not isinstance(encoded, str) or not encoded:
        message = payload.get("error") or payload.get("message") or "missing audio_base64"
        raise RuntimeError(f"custom TTS API error: {message}")
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("custom TTS JSON response contains invalid base64 audio") from exc
    audio_format = payload.get("format", default_format)
    if not isinstance(audio_format, str) or not audio_format:
        raise RuntimeError("custom TTS response format must be a non-empty string")
    return audio, audio_format.lower()


def _is_audio_content_type(content_type: str) -> bool:
    return content_type in _CONTENT_FORMATS or content_type.startswith("audio/")


def _format_from_content_type(content_type: str, default: str) -> str:
    if content_type in _CONTENT_FORMATS:
        return _CONTENT_FORMATS[content_type]
    if content_type.startswith("audio/"):
        return content_type.split("/", 1)[1]
    return default
