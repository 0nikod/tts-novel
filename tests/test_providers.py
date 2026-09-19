import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from novel_tts.renderer.http import TTSRequestError
from novel_tts.renderer.models import CompiledStyle, RenderProfile, Voice
from novel_tts.renderer.providers import ProviderRunner, get_provider


def config(
    tmp_path: Path,
    *,
    provider: str = "custom",
    model: str = "private-model",
    request: dict[str, object] | None = None,
    retries: int = 1,
) -> RenderProfile:
    return RenderProfile(
        id=f"{provider}-test",
        provider=provider,
        endpoint=(
            "https://api.xiaomimimo.com/v1/chat/completions"
            if provider == "mimo"
            else "https://private.test/v1/tts"
        ),
        model=model,
        api_key_env="PRIVATE_KEY",
        request=request or {},
        retries=retries,
    )


def test_custom_provider_preserves_contract_and_decodes_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["accept"] == "audio/*, application/json"
        payload = json.loads(request.content)
        assert payload["model"] == "private-model"
        assert payload["voice"] == {"reference_id": "ref-1", "id": "voice-1"}
        assert payload["style"] == {
            "direction": "平静、克制地朗读。",
            "tags_before": ["深呼吸"],
        }
        return httpx.Response(
            200,
            json={
                "audio_base64": base64.b64encode(b"audio").decode(),
                "format": "wav",
            },
        )

    cfg = config(tmp_path, request={"response_kind": "json"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ProviderRunner(tmp_path, cfg, get_provider("custom"), client).synthesize(
            text="正文",
            voice=Voice("voice-1", cfg.id, {"reference_id": "ref-1"}),
            style=CompiledStyle(
                text="正文",
                instruction="平静、克制地朗读。",
                values={
                    "direction": "平静、克制地朗读。",
                    "tags_before": ["深呼吸"],
                },
            ),
        )

    assert result.audio == b"audio"
    assert result.audio_format == "wav"


def test_custom_provider_requires_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"should-not-run")

    cfg = config(tmp_path)
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(TTSRequestError, match="PRIVATE_KEY") as caught,
    ):
        ProviderRunner(tmp_path, cfg, get_provider("custom"), client).synthesize(
            text="text",
            voice=Voice("v", cfg.id, {"reference_id": "ref"}),
            style=CompiledStyle(text="text"),
        )

    assert calls == 0
    assert caught.value.attempts == 0


@pytest.mark.parametrize("retry_status", [429, 500, 501, 599])
def test_http_runner_retries_retryable_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retry_status: int,
) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")
    monkeypatch.setattr("novel_tts.renderer.http._backoff", lambda _attempt: None)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(retry_status, text="retry")
        return httpx.Response(200, content=b"wave", headers={"content-type": "audio/wav"})

    cfg = config(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ProviderRunner(tmp_path, cfg, get_provider("custom"), client).synthesize(
            text="text",
            voice=Voice("v", cfg.id, {"reference_id": "ref"}),
            style=CompiledStyle(text="text"),
        )

    assert calls == 2
    assert result.attempts == 2


def test_http_runner_does_not_retry_ordinary_api_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "bad request"})

    cfg = config(tmp_path, retries=3)
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(TTSRequestError, match="HTTP 400") as caught,
    ):
        ProviderRunner(tmp_path, cfg, get_provider("custom"), client).synthesize(
            text="text",
            voice=Voice("v", cfg.id, {"reference_id": "ref"}),
            style=CompiledStyle(text="text"),
        )

    assert calls == 1
    assert caught.value.attempts == 1


def test_mimo_nonstream_payload_and_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["api-key"] == "secret"
        assert "authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload == {
            "model": "mimo-v2.5-tts",
            "messages": [
                {"role": "user", "content": "平静、克制地朗读。"},
                {"role": "assistant", "content": "（叹气）正文"},
            ],
            "audio": {"format": "wav", "voice": "冰糖"},
            "stream": False,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"audio": {"data": _b64(b"wave")}}}]},
        )

    cfg = config(
        tmp_path,
        provider="mimo",
        model="mimo-v2.5-tts",
        request={"format": "wav", "stream": False},
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ProviderRunner(tmp_path, cfg, get_provider("mimo"), client).synthesize(
            text="正文",
            voice=Voice("narrator", cfg.id, {"mode": "preset", "voice": "冰糖"}),
            style=CompiledStyle(text="（叹气）正文", instruction="平静、克制地朗读。"),
        )

    assert result.audio == b"wave"
    assert result.audio_format == "wav"


def test_mimo_stream_concatenates_pcm16_sse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")
    events = b"".join(
        [
            b'data: {"choices":[{"delta":{"audio":{"data":"YWE="}}}]}\n\n',
            b'data: {"choices":[{"delta":{"audio":{"data":"YmI="}}}]}\n\n',
            b"data: [DONE]\n\n",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["audio"]["format"] == "pcm16"
        assert payload["stream"] is True
        return httpx.Response(200, content=events, headers={"content-type": "text/event-stream"})

    cfg = config(
        tmp_path,
        provider="mimo",
        model="mimo-v2.5-tts",
        request={"format": "pcm16", "stream": True},
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ProviderRunner(tmp_path, cfg, get_provider("mimo"), client).synthesize(
            text="正文",
            voice=Voice("narrator", cfg.id, {"mode": "preset", "voice": "冰糖"}),
            style=CompiledStyle(text="正文"),
        )

    assert result.audio == b"aabb"
    assert result.audio_format == "pcm16"
    assert result.input_sample_rate == 24000


def test_mimo_voice_design_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"] == [
            {
                "role": "user",
                "content": "年轻女声\n音色自然\n语速放慢，保持克制。",
            },
            {"role": "assistant", "content": "正文"},
        ]
        assert payload["audio"] == {
            "format": "wav",
            "optimize_text_preview": True,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"audio": {"data": _b64(b"wave")}}}]},
        )

    cfg = config(
        tmp_path,
        provider="mimo",
        model="mimo-v2.5-tts-voicedesign",
        request={"format": "wav", "optimize_text_preview": True},
    )
    voice = Voice(
        "designed",
        cfg.id,
        {"mode": "design", "description": "年轻女声", "instruction": "音色自然"},
    )
    assert get_provider("mimo").validate_voice(tmp_path, cfg, voice) == []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ProviderRunner(tmp_path, cfg, get_provider("mimo"), client).synthesize(
            text="正文",
            voice=voice,
            style=CompiledStyle(text="正文", instruction="语速放慢，保持克制。"),
        )
    assert result.audio == b"wave"


def test_mimo_voice_clone_data_url_and_cache_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "secret")
    reference = tmp_path / "voice.mp3"
    reference.write_bytes(b"reference-audio")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        data_url = payload["audio"]["voice"]
        assert data_url.startswith("data:audio/mpeg;base64,")
        assert base64.b64decode(data_url.split(",", 1)[1]) == b"reference-audio"
        assert payload["messages"] == [{"role": "assistant", "content": "正文"}]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"audio": {"data": _b64(b"wave")}}}]},
        )

    cfg = config(
        tmp_path,
        provider="mimo",
        model="mimo-v2.5-tts-voiceclone",
        request={"format": "wav"},
    )
    voice = Voice("cloned", cfg.id, {"mode": "clone", "reference_audio": "voice.mp3"})
    adapter = get_provider("mimo")
    assert adapter.validate_voice(tmp_path, cfg, voice) == []
    assert adapter.voice_cache_data(tmp_path, cfg, voice)["reference_audio"] == {
        "name": "voice.mp3",
        "sha256": hashlib.sha256(b"reference-audio").hexdigest(),
    }

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ProviderRunner(tmp_path, cfg, adapter, client).synthesize(
            text="正文", voice=voice, style=CompiledStyle(text="正文")
        )
    assert result.audio == b"wave"


def test_mimo_rejects_voice_mode_model_mismatch(tmp_path: Path) -> None:
    cfg = config(
        tmp_path,
        provider="mimo",
        model="mimo-v2.5-tts-voicedesign",
    )
    voice = Voice("wrong", cfg.id, {"mode": "preset", "voice": "冰糖"})

    errors = get_provider("mimo").validate_voice(tmp_path, cfg, voice)

    assert any("mode must be 'design'" in error for error in errors)


def test_mimo_requires_api_key_before_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    cfg = config(tmp_path, provider="mimo", model="mimo-v2.5-tts")
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(TTSRequestError, match="PRIVATE_KEY") as caught,
    ):
        ProviderRunner(tmp_path, cfg, get_provider("mimo"), client).synthesize(
            text="正文",
            voice=Voice("narrator", cfg.id, {"mode": "preset", "voice": "冰糖"}),
            style=CompiledStyle(text="正文"),
        )
    assert calls == 0
    assert caught.value.attempts == 0


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")
