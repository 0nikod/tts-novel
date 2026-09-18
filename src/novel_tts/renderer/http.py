from __future__ import annotations

import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .models import PreparedRequest

RETRYABLE_STATUS = {429, 502, 503, 504}


@dataclass(frozen=True)
class HttpResult:
    body: bytes
    request_id: str | None
    attempts: int
    elapsed_ms: int


class TTSRequestError(ValueError):
    def __init__(self, message: str, *, attempts: int, elapsed_ms: int) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms


def send_request(
    request: PreparedRequest,
    *,
    timeout: float,
    retries: int,
    client: httpx.Client | None = None,
    transport: httpx.BaseTransport | None = None,
) -> HttpResult:
    if client is not None and transport is not None:
        raise ValueError("send_request cannot receive both client and transport")
    owned_client = client is None
    current_client = client or httpx.Client(timeout=timeout, transport=transport)
    started = time.monotonic()
    attempts = 0
    try:
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                response = current_client.post(
                    request.url,
                    headers=request.headers,
                    json=request.json_body,
                    content=request.content,
                    timeout=timeout,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
                if attempt < retries:
                    time.sleep(_retry_delay(None, attempt))
                    continue
                raise TTSRequestError(
                    f"TTS API connection failed after {attempts} attempt(s): {error}",
                    attempts=attempts,
                    elapsed_ms=_elapsed_ms(started),
                ) from error
            except (
                httpx.ReadError,
                httpx.ReadTimeout,
                httpx.WriteError,
                httpx.WriteTimeout,
                httpx.RemoteProtocolError,
            ) as error:
                raise TTSRequestError(
                    "TTS API request outcome is uncertain; it was not retried to avoid a "
                    f"duplicate paid request: {error}",
                    attempts=attempts,
                    elapsed_ms=_elapsed_ms(started),
                ) from error

            if response.status_code in RETRYABLE_STATUS and attempt < retries:
                time.sleep(_retry_delay(response.headers.get("Retry-After"), attempt))
                continue
            if response.is_error:
                detail = _safe_error_detail(response)
                raise TTSRequestError(
                    f"TTS API returned HTTP {response.status_code}: {detail}",
                    attempts=attempts,
                    elapsed_ms=_elapsed_ms(started),
                )
            request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
            return HttpResult(
                body=response.content,
                request_id=request_id,
                attempts=attempts,
                elapsed_ms=_elapsed_ms(started),
            )
    finally:
        if owned_client:
            current_client.close()
    raise AssertionError("unreachable")


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(retry_after).timestamp() - time.time())
            except (TypeError, ValueError):
                pass
    return min(30.0, 2**attempt + random.random())


def _safe_error_detail(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            data: Any = response.json()
            text = str(data)
        except ValueError:
            text = response.text
    else:
        text = response.text
    return text[:500].replace("\n", " ") or "no response body"
