from __future__ import annotations

import base64
import os
import time
from typing import Any

import httpx

from .models import AudioResult, RenderConfig, Voice

_CONTENT_FORMATS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/mp4": "m4a",
    "application/octet-stream": "wav",
}


class CustomTTSError(ValueError):
    def __init__(self, message: str, *, attempts: int, elapsed_ms: int) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms


class CustomTTS:
    """The only module that knows the private TTS HTTP contract.

    Requests use a compact JSON body containing ``model``, ``text``, ``voice``,
    and compiled ``style``. The endpoint may return audio bytes directly or JSON
    with ``audio_base64`` (or ``audio``) and an optional ``format``.
    """

    def __init__(self, config: RenderConfig, *, client: httpx.Client | None = None) -> None:
        self.config = config
        self._owned_client = client is None
        self._client = client or httpx.Client(timeout=config.timeout_seconds)

    def close(self) -> None:
        if self._owned_client and self._client is not None:
            self._client.close()
            self._client = None

    def synthesize(
        self,
        *,
        text: str,
        voice: Voice,
        style: dict[str, Any] | None,
    ) -> AudioResult:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise CustomTTSError(
                f"environment variable {self.config.api_key_env} is not set",
                attempts=0,
                elapsed_ms=0,
            )
        client = self._client
        if client is None:
            raise CustomTTSError("custom TTS client is closed", attempts=0, elapsed_ms=0)
        payload = {
            "model": self.config.model,
            "text": text,
            "voice": {**voice.parameters, "id": voice.id},
            "style": style or {},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "audio/*, application/json",
        }
        started = time.monotonic()
        attempts = 0
        for attempt in range(self.config.retries + 1):
            attempts = attempt + 1
            try:
                response = client.post(
                    self.config.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
            except httpx.TransportError as error:
                if attempt < self.config.retries:
                    time.sleep(min(2**attempt, 5))
                    continue
                raise CustomTTSError(
                    f"custom TTS connection failed after {attempts} attempt(s): {error}",
                    attempts=attempts,
                    elapsed_ms=_elapsed_ms(started),
                ) from error

            retryable = response.status_code == 429 or 500 <= response.status_code < 600
            if retryable and attempt < self.config.retries:
                time.sleep(_retry_delay(response, attempt))
                continue
            if response.is_error:
                raise CustomTTSError(
                    f"custom TTS returned HTTP {response.status_code}: {_error_detail(response)}",
                    attempts=attempts,
                    elapsed_ms=_elapsed_ms(started),
                )
            audio, audio_format = _decode_response(response)
            request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
            return AudioResult(
                audio=audio,
                audio_format=audio_format,
                request_id=request_id,
                attempts=attempts,
                elapsed_ms=_elapsed_ms(started),
            )
        raise AssertionError("unreachable")

    def __enter__(self) -> CustomTTS:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _decode_response(response: httpx.Response) -> tuple[bytes, str]:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type in _CONTENT_FORMATS or content_type.startswith("audio/"):
        if not response.content:
            raise ValueError("custom TTS returned empty audio")
        return response.content, _CONTENT_FORMATS.get(content_type, content_type.split("/", 1)[1])
    try:
        data: Any = response.json()
    except ValueError as error:
        raise ValueError("custom TTS response is neither audio nor JSON") from error
    if not isinstance(data, dict):
        raise ValueError("custom TTS JSON response must be a mapping")
    encoded = data.get("audio_base64", data.get("audio"))
    if not isinstance(encoded, str) or not encoded:
        message = data.get("error") or data.get("message") or "missing audio_base64"
        raise ValueError(f"custom TTS API error: {message}")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("custom TTS returned invalid base64 audio") from error
    audio_format = data.get("format", "wav")
    if not isinstance(audio_format, str) or not audio_format:
        raise ValueError("custom TTS response format must be a string")
    return audio, audio_format


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return max(0.0, min(float(retry_after), 30.0))
        except ValueError:
            pass
    return min(2**attempt, 5)


def _error_detail(response: httpx.Response) -> str:
    try:
        detail = (
            response.json() if "json" in response.headers.get("content-type", "") else response.text
        )
    except ValueError:
        detail = response.text
    return str(detail).replace("\n", " ")[:500] or "no response body"


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
