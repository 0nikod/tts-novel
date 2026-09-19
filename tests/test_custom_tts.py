import base64
from pathlib import Path

import httpx
import pytest

from novel_tts.renderer.custom_tts import CustomTTS, CustomTTSError
from novel_tts.renderer.models import RenderConfig, Voice


def config(tmp_path: Path, *, retries: int = 1) -> RenderConfig:
    return RenderConfig(
        root=tmp_path,
        endpoint="https://private.test/v1/tts",
        model="private-model",
        api_key_env="PRIVATE_KEY",
        retries=retries,
    )


def test_custom_tts_payload_and_json_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert b'"model":"private-model"' in request.content
        assert b'"reference_id":"ref-1"' in request.content
        return httpx.Response(
            200,
            json={
                "audio_base64": base64.b64encode(b"audio").decode(),
                "format": "wav",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = CustomTTS(config(tmp_path), client=client).synthesize(
            text="正文",
            voice=Voice("voice-1", {"reference_id": "ref-1"}),
            style={"emotion": "calm"},
        )

    assert result.audio == b"audio"
    assert result.audio_format == "wav"


def test_custom_tts_retries_5xx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")
    monkeypatch.setattr("novel_tts.renderer.custom_tts.time.sleep", lambda _seconds: None)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(501, text="retry")
        return httpx.Response(200, content=b"wave", headers={"content-type": "audio/wav"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = CustomTTS(config(tmp_path), client=client).synthesize(
            text="text", voice=Voice("v"), style=None
        )

    assert calls == 2
    assert result.attempts == 2


def test_custom_tts_does_not_retry_ordinary_api_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "bad request"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(CustomTTSError, match="HTTP 400"),
    ):
        CustomTTS(config(tmp_path, retries=3), client=client).synthesize(
            text="text", voice=Voice("v"), style=None
        )

    assert calls == 1
