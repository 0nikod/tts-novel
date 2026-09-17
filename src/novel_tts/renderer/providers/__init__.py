from __future__ import annotations

from .base import ProviderDriver
from .fish import FishAudioDriver
from .mimo import MimoDriver


def get_driver(provider: str) -> ProviderDriver:
    if provider == "fish_audio":
        return FishAudioDriver()
    if provider == "mimo":
        return MimoDriver()
    raise ValueError(f"unsupported TTS provider: {provider}")


__all__ = ["ProviderDriver", "get_driver"]
