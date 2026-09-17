from __future__ import annotations

import random
import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .models import PreparedRequest

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def send_request(
    request: PreparedRequest,
    *,
    timeout: float,
    retries: int,
    transport: httpx.BaseTransport | None = None,
) -> tuple[bytes, str | None]:
    last_error: Exception | None = None
    with httpx.Client(timeout=timeout, transport=transport) as client:
        for attempt in range(retries + 1):
            try:
                response = client.post(
                    request.url,
                    headers=request.headers,
                    json=request.json_body,
                    content=request.content,
                )
                if response.status_code in RETRYABLE_STATUS and attempt < retries:
                    time.sleep(_retry_delay(response.headers.get("Retry-After"), attempt))
                    continue
                if response.is_error:
                    detail = _safe_error_detail(response)
                    raise ValueError(f"TTS API returned HTTP {response.status_code}: {detail}")
                request_id = response.headers.get("x-request-id") or response.headers.get(
                    "request-id"
                )
                return response.content, request_id
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                last_error = error
                if attempt >= retries:
                    break
                time.sleep(_retry_delay(None, attempt))
    raise ValueError(f"TTS API request failed after {retries + 1} attempt(s): {last_error}")


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
