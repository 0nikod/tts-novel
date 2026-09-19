from __future__ import annotations

from pathlib import Path

from novel_tts.renderer.models import RenderProfile
from novel_tts.renderer.providers.base import ProviderAdapter, ProviderRunner
from novel_tts.renderer.providers.custom import CustomProvider
from novel_tts.renderer.providers.mimo import MimoProvider

_PROVIDERS: dict[str, ProviderAdapter] = {
    adapter.id: adapter for adapter in (CustomProvider(), MimoProvider())
}


def provider_ids() -> tuple[str, ...]:
    return tuple(sorted(_PROVIDERS))


def get_provider(provider: str) -> ProviderAdapter:
    try:
        return _PROVIDERS[provider]
    except KeyError as exc:
        raise ValueError(
            f"unknown TTS provider {provider!r}; choose from: {', '.join(provider_ids())}"
        ) from exc


def create_runner(render_root: Path, profile: RenderProfile) -> ProviderRunner:
    return ProviderRunner(render_root, profile, get_provider(profile.provider))


__all__ = [
    "ProviderAdapter",
    "ProviderRunner",
    "create_runner",
    "get_provider",
    "provider_ids",
]
