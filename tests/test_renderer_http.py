import httpx
import pytest

from novel_tts.renderer.http import send_request
from novel_tts.renderer.models import PreparedRequest


def test_send_request_uses_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test"
        return httpx.Response(200, content=b"audio", headers={"x-request-id": "request-1"})

    body, request_id = send_request(
        PreparedRequest(
            url="https://example.test/tts",
            headers={"Authorization": "Bearer test"},
            json_body={"text": "测试"},
        ),
        timeout=5,
        retries=0,
        transport=httpx.MockTransport(handler),
    )

    assert body == b"audio"
    assert request_id == "request-1"


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
