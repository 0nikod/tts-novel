from __future__ import annotations

import random
import time
from typing import Any

import httpx

from novel_tts.renderer.models import HttpResult, PreparedRequest

_RETRYABLE_STATUS = {408, 409, 429}


class TTSRequestError(RuntimeError):
    def __init__(self, message: str, *, attempts: int, elapsed_ms: int) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms


def send_request(
    request: PreparedRequest,
    *,
    timeout_seconds: float,
    retries: int,
    client: httpx.Client | Any | None = None,
) -> HttpResult:
    owned_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds)
    started = time.monotonic()
    last_error: Exception | None = None

    try:
        for attempt in range(1, retries + 2):
            try:
                response = http_client.post(
                    request.url,
                    headers=request.headers,
                    json=request.json_body,
                    timeout=timeout_seconds,
                )
                retryable = (
                    response.status_code in _RETRYABLE_STATUS or 500 <= response.status_code < 600
                )
                if retryable and attempt <= retries:
                    _backoff(attempt)
                    continue
                response.raise_for_status()
                return HttpResult(
                    body=response.content,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    request_id=_request_id(response),
                    attempts=attempt,
                    elapsed_ms=_elapsed_ms(started),
                )
            except httpx.TransportError as exc:
                last_error = exc
                if attempt > retries:
                    break
                _backoff(attempt)
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:500]
                raise TTSRequestError(
                    f"TTS request failed with HTTP {exc.response.status_code}: {body}",
                    attempts=attempt,
                    elapsed_ms=_elapsed_ms(started),
                ) from exc
    finally:
        if owned_client:
            http_client.close()

    raise TTSRequestError(
        f"TTS request failed after {retries + 1} attempts: {last_error}",
        attempts=retries + 1,
        elapsed_ms=_elapsed_ms(started),
    )


def _backoff(attempt: int) -> None:
    delay = min(0.5 * (2 ** (attempt - 1)), 4.0)
    time.sleep(delay + random.uniform(0, delay * 0.2))


def _request_id(response: httpx.Response) -> str | None:
    for name in ("x-request-id", "request-id", "x-trace-id"):
        value = response.headers.get(name)
        if value:
            return value
    return None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
