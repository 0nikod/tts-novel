from __future__ import annotations

import base64
import json
import mimetypes
from typing import Any

from ..models import PreparedRequest, ProviderResult, RenderJob, VoiceMode
from .base import ProviderDriver

_ALLOWED_FIELDS = {"format", "stream", "optimize_text_preview"}


class MimoDriver(ProviderDriver):
    endpoint = "https://api.xiaomimimo.com/v1/chat/completions"

    def validate_profile(self, job: RenderJob) -> None:
        request = job.profile.request
        extra = set(request) - _ALLOWED_FIELDS
        if extra:
            raise ValueError("unsupported MiMo request fields: " + ", ".join(sorted(extra)))
        stream = request.get("stream", False)
        audio_format = request.get("format", "wav")
        if stream and audio_format != "pcm16":
            raise ValueError("MiMo streaming requires format: pcm16")
        optimize = request.get("optimize_text_preview", False)
        if optimize and job.voice.kind != VoiceMode.TEXT_DESIGN:
            raise ValueError("MiMo optimize_text_preview is only valid for text_design")

    def prepare(self, job: RenderJob, api_key: str) -> PreparedRequest:
        self.validate_profile(job)
        stream = bool(job.profile.request.get("stream", False))
        audio_format = str(job.profile.request.get("format", "wav"))
        messages: list[dict[str, str]] = []
        audio: dict[str, Any] = {"format": audio_format}

        instruction = job.compiled.instruction
        if job.voice.kind == VoiceMode.PRESET:
            audio["voice"] = job.voice.voice
            if instruction:
                messages.append({"role": "user", "content": instruction})
        elif job.voice.kind == VoiceMode.TEXT_DESIGN:
            design = job.voice.description or ""
            content = design if instruction is None else f"{design}\n表演要求：{instruction}"
            messages.append({"role": "user", "content": content})
            if job.profile.request.get("optimize_text_preview", False):
                audio["optimize_text_preview"] = True
        elif job.voice.kind == VoiceMode.INLINE_CLONE:
            assert job.voice.reference_audio is not None
            audio["voice"] = _audio_data_uri(job.voice.reference_audio)
            if instruction:
                messages.append({"role": "user", "content": instruction})
        else:
            raise ValueError(f"MiMo does not support voice kind {job.voice.kind}")

        # Renderer jobs always carry source text, so preserve it even for voice design.
        messages.append({"role": "assistant", "content": job.compiled.text})
        payload = {
            "model": job.profile.model,
            "messages": messages,
            "audio": audio,
            "stream": stream,
        }
        return PreparedRequest(
            url=self.endpoint,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json_body=payload,
            response_kind="base64_sse" if stream else "base64_json",
            audio_format=audio_format,
        )

    def decode(self, request: PreparedRequest, body: bytes) -> ProviderResult:
        if request.response_kind == "base64_sse":
            audio = _decode_sse_audio(body)
        else:
            try:
                data = json.loads(body)
                encoded = data["choices"][0]["message"]["audio"]["data"]
                audio = base64.b64decode(encoded, validate=True)
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError("MiMo response does not contain valid audio data") from error
        if not audio:
            raise ValueError("MiMo returned empty audio")
        return ProviderResult(audio=audio, audio_format=request.audio_format)


def _audio_data_uri(path: Any) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if str(path).lower().endswith(".wav"):
        mime = "audio/wav"
    elif mime not in {"audio/mpeg", "audio/mp3"}:
        mime = "audio/mpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _decode_sse_audio(body: bytes) -> bytes:
    output = bytearray()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload == b"[DONE]":
            break
        try:
            event = json.loads(payload)
            encoded = event["choices"][0]["delta"]["audio"]["data"]
            output.extend(base64.b64decode(encoded, validate=True))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return bytes(output)
