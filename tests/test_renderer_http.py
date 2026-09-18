import httpx
import pytest

from novel_tts.renderer.http import send_request
from novel_tts.renderer.models import PreparedRequest


def test_send_request_uses_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test"
        return httpx.Response(200, content=b"audio", headers={"x-request-id": "request-1"})

    result = send_request(
        PreparedRequest(
            url="https://example.test/tts",
            headers={"Authorization": "Bearer test"},
            json_body={"text": "测试"},
        ),
        timeout=5,
        retries=0,
        transport=httpx.MockTransport(handler),
    )

    assert result.body == b"audio"
    assert result.request_id == "request-1"
    assert result.attempts == 1
    assert result.elapsed_ms >= 0


def test_send_request_records_retry_attempts() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, content=b"audio")

    result = send_request(
        PreparedRequest(url="https://example.test/tts", headers={}),
        timeout=5,
        retries=1,
        transport=httpx.MockTransport(handler),
    )

    assert result.attempts == 2
    assert attempts == 2


def test_send_request_does_not_retry_uncertain_read_timeout() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timed out after sending", request=request)

    with pytest.raises(ValueError, match="not retried.*duplicate paid request"):
        send_request(
            PreparedRequest(url="https://example.test/tts", headers={}),
            timeout=5,
            retries=4,
            transport=httpx.MockTransport(handler),
        )

    assert attempts == 1


def test_send_request_reports_bounded_api_error() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            400,
            json={"error": "invalid voice"},
            headers={"content-type": "application/json"},
        )
    )

    with pytest.raises(ValueError, match="HTTP 400.*invalid voice"):
        send_request(
            PreparedRequest(url="https://example.test/tts", headers={}),
            timeout=5,
            retries=0,
            transport=transport,
        )
