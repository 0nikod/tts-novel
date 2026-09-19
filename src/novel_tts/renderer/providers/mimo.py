from __future__ import annotations

import base64
import binascii
import hashlib
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

MIMO_ENDPOINT = "https://api.xiaomimimo.com/v1/chat/completions"
MIMO_MODELS = (
    "mimo-v2.5-tts",
    "mimo-v2.5-tts-voicedesign",
    "mimo-v2.5-tts-voiceclone",
)
MIMO_MODEL_MODES = {
    "mimo-v2.5-tts": "preset",
    "mimo-v2.5-tts-voicedesign": "design",
    "mimo-v2.5-tts-voiceclone": "clone",
}
MIMO_PRESET_VOICES = (
    "mimo_default",
    "冰糖",
    "茉莉",
    "苏打",
    "白桦",
    "Mia",
    "Chloe",
    "Milo",
    "Dean",
)
_MAX_CLONE_BASE64_BYTES = 10 * 1024 * 1024


class MimoProvider(ProviderAdapter):
    id = "mimo"
    default_endpoint = MIMO_ENDPOINT
    models = MIMO_MODELS

    def validate_profile(self, profile: RenderProfile) -> list[str]:
        errors: list[str] = []
        if profile.model not in MIMO_MODELS:
            errors.append("mimo model must be one of: " + ", ".join(MIMO_MODELS))
        allowed = {"format", "stream", "optimize_text_preview"}
        unknown = sorted(set(profile.request) - allowed)
        if unknown:
            errors.append(f"mimo request has unknown keys: {', '.join(unknown)}")

        audio_format = profile.request.get("format", "wav")
        if audio_format not in {"wav", "mp3", "pcm", "pcm16"}:
            errors.append("mimo request.format must be wav, mp3, pcm, or pcm16")
        stream = profile.request.get("stream", False)
        if not isinstance(stream, bool):
            errors.append("mimo request.stream must be a boolean")
        elif stream and audio_format not in {"pcm", "pcm16"}:
            errors.append("mimo streaming requires request.format: pcm16")

        optimize = profile.request.get("optimize_text_preview", False)
        if not isinstance(optimize, bool):
            errors.append("mimo request.optimize_text_preview must be a boolean")
        elif optimize and profile.model != "mimo-v2.5-tts-voicedesign":
            errors.append(
                "mimo optimize_text_preview is supported only by mimo-v2.5-tts-voicedesign"
            )
        return errors

    def validate_voice(self, render_root: Path, profile: RenderProfile, voice: Voice) -> list[str]:
        params = voice.parameters
        expected_mode = MIMO_MODEL_MODES.get(profile.model)
        mode = params.get("mode")
        mode_errors: list[str] = []
        if mode != expected_mode:
            mode_errors.append(
                f"voice {voice.id!r} mode must be {expected_mode!r} for model {profile.model!r}"
            )

        if profile.model == "mimo-v2.5-tts":
            allowed = {"mode", "voice", "instruction"}
            errors = mode_errors + _unknown_voice_keys(voice, allowed)
            preset = params.get("voice")
            if preset not in MIMO_PRESET_VOICES:
                errors.append(
                    f"voice {voice.id!r} must set voice to a MiMo preset: "
                    + ", ".join(MIMO_PRESET_VOICES)
                )
            return errors

        if profile.model == "mimo-v2.5-tts-voicedesign":
            errors = mode_errors + _unknown_voice_keys(
                voice, {"mode", "description", "instruction"}
            )
            if not _nonempty_string(params.get("description")):
                errors.append(
                    f"voice {voice.id!r} must set a non-empty description for MiMo voice design"
                )
            return errors

        if profile.model == "mimo-v2.5-tts-voiceclone":
            errors = mode_errors + _unknown_voice_keys(
                voice, {"mode", "reference_audio", "instruction"}
            )
            value = params.get("reference_audio")
            if not _nonempty_string(value):
                errors.append(f"voice {voice.id!r} must set reference_audio for MiMo voice clone")
                return errors
            path = _reference_path(render_root, str(value))
            if path.suffix.lower() not in {".mp3", ".wav"}:
                errors.append(f"voice {voice.id!r} reference_audio must be an mp3 or wav file")
            elif not path.is_file():
                errors.append(f"voice {voice.id!r} reference_audio does not exist: {path}")
            elif _clone_data_uri_size(path) > _MAX_CLONE_BASE64_BYTES:
                errors.append(
                    f"voice {voice.id!r} reference_audio exceeds MiMo's 10 MB base64 limit"
                )
            return errors

        return []

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
        del text
        if not api_key:
            raise TTSRequestError(
                f"environment variable {profile.api_key_env!r} is not set for MiMo",
                attempts=0,
                elapsed_ms=0,
            )

        instruction_parts = [
            value
            for value in (
                voice.parameters.get("description")
                if profile.model == "mimo-v2.5-tts-voicedesign"
                else None,
                voice.parameters.get("instruction"),
                style.instruction,
            )
            if _nonempty_string(value)
        ]
        messages: list[dict[str, str]] = []
        if instruction_parts or profile.model == "mimo-v2.5-tts-voicedesign":
            messages.append({"role": "user", "content": "\n".join(instruction_parts)})
        messages.append({"role": "assistant", "content": style.text})

        audio_format = str(profile.request.get("format", "wav"))
        audio: dict[str, Any] = {"format": audio_format}
        if profile.model == "mimo-v2.5-tts":
            audio["voice"] = voice.parameters["voice"]
        elif profile.model == "mimo-v2.5-tts-voiceclone":
            audio["voice"] = _clone_data_uri(
                _reference_path(render_root, str(voice.parameters["reference_audio"]))
            )
        if "optimize_text_preview" in profile.request:
            audio["optimize_text_preview"] = profile.request["optimize_text_preview"]

        stream = bool(profile.request.get("stream", False))
        return PreparedRequest(
            url=profile.endpoint,
            headers={
                "Content-Type": "application/json",
                "api-key": api_key,
            },
            json_body={
                "model": profile.model,
                "messages": messages,
                "audio": audio,
                "stream": stream,
            },
            response_kind="sse" if stream else "json",
            audio_format="pcm16" if audio_format == "pcm" else audio_format,
            input_sample_rate=24000 if audio_format in {"pcm", "pcm16"} else None,
        )

    def decode_response(self, request: PreparedRequest, response: HttpResult) -> AudioResult:
        if request.response_kind == "sse":
            audio = _decode_sse(response.body)
        else:
            audio = _decode_nonstream(response.body)
        return AudioResult(
            audio=audio,
            audio_format=request.audio_format,
            input_sample_rate=request.input_sample_rate,
            request_id=response.request_id,
            attempts=response.attempts,
            elapsed_ms=response.elapsed_ms,
        )

    def voice_cache_data(
        self, render_root: Path, profile: RenderProfile, voice: Voice
    ) -> dict[str, Any]:
        del profile
        data = dict(voice.parameters)
        reference_audio = data.get("reference_audio")
        if _nonempty_string(reference_audio):
            path = _reference_path(render_root, str(reference_audio))
            if path.is_file():
                data["reference_audio"] = {
                    "name": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
        return data


def _decode_nonstream(body: bytes) -> bytes:
    try:
        payload = json.loads(body)
        encoded = payload["choices"][0]["message"]["audio"]["data"]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("MiMo response did not contain choices[0].message.audio.data") from exc
    return _decode_base64(encoded, "MiMo response")


def _decode_sse(body: bytes) -> bytes:
    chunks: list[bytes] = []
    for raw_line in body.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
            choices = event.get("choices") or []
            if not choices:
                continue
            audio = (choices[0].get("delta") or {}).get("audio")
            if isinstance(audio, dict) and audio.get("data"):
                chunks.append(_decode_base64(audio["data"], "MiMo SSE response"))
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            raise RuntimeError("MiMo returned an invalid SSE event") from exc
    if not chunks:
        raise RuntimeError("MiMo SSE response contained no audio chunks")
    return b"".join(chunks)


def _decode_base64(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} contained empty audio data")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(f"{label} contained invalid base64 audio") from exc


def _clone_data_uri(path: Path) -> str:
    mime = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    value = f"data:{mime};base64,{encoded}"
    if len(value.encode("ascii")) > _MAX_CLONE_BASE64_BYTES:
        raise RuntimeError("MiMo clone reference exceeds the 10 MB base64 limit")
    return value


def _reference_path(render_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else render_root / path


def _unknown_voice_keys(voice: Voice, allowed: set[str]) -> list[str]:
    unknown = sorted(set(voice.parameters) - allowed)
    if not unknown:
        return []
    return [f"voice {voice.id!r} has unknown MiMo keys: {', '.join(unknown)}"]


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _clone_data_uri_size(path: Path) -> int:
    mime = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    prefix_size = len(f"data:{mime};base64,")
    encoded_size = 4 * ((path.stat().st_size + 2) // 3)
    return prefix_size + encoded_size
