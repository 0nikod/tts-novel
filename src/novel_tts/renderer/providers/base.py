from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from novel_tts.renderer.http import send_request
from novel_tts.renderer.models import (
    AudioResult,
    CompiledStyle,
    HttpResult,
    PreparedRequest,
    RenderProfile,
    Voice,
)


class ProviderAdapter(ABC):
    id: str
    default_endpoint: str | None = None
    models: tuple[str, ...] = ()

    @abstractmethod
    def validate_profile(self, profile: RenderProfile) -> list[str]:
        """Return profile configuration errors."""

    @abstractmethod
    def validate_voice(self, render_root: Path, profile: RenderProfile, voice: Voice) -> list[str]:
        """Return errors for one provider-specific voice source."""

    @abstractmethod
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
        """Translate the provider-neutral render job into an HTTP request."""

    @abstractmethod
    def decode_response(self, request: PreparedRequest, response: HttpResult) -> AudioResult:
        """Decode one successful HTTP response into audio."""

    def voice_cache_data(
        self, render_root: Path, profile: RenderProfile, voice: Voice
    ) -> dict[str, Any]:
        del render_root, profile
        return voice.parameters


class ProviderRunner:
    def __init__(
        self,
        render_root: Path,
        profile: RenderProfile,
        adapter: ProviderAdapter,
        client: httpx.Client | Any | None = None,
    ) -> None:
        self.render_root = render_root
        self.profile = profile
        self.adapter = adapter
        self._owned_client = client is None
        self.client = client or httpx.Client(timeout=profile.timeout_seconds)

    def close(self) -> None:
        if self._owned_client and self.client is not None:
            self.client.close()
            self.client = None

    def __enter__(self) -> ProviderRunner:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def synthesize(
        self,
        *,
        text: str,
        voice: Voice,
        style: CompiledStyle,
    ) -> AudioResult:
        if self.client is None:
            raise RuntimeError("TTS provider runner is closed")
        if voice.profile_id != self.profile.id:
            raise RuntimeError(
                f"voice {voice.id!r} belongs to profile {voice.profile_id!r}, "
                f"not {self.profile.id!r}"
            )
        api_key = os.environ.get(self.profile.api_key_env)
        request = self.adapter.prepare_request(
            self.render_root,
            self.profile,
            text=text,
            voice=voice,
            style=style,
            api_key=api_key,
        )
        response = send_request(
            request,
            timeout_seconds=self.profile.timeout_seconds,
            retries=self.profile.retries,
            client=self.client,
        )
        return self.adapter.decode_response(request, response)
