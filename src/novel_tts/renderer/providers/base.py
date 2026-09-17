from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import PreparedRequest, ProviderResult, RenderJob


class ProviderDriver(ABC):
    @abstractmethod
    def validate_profile(self, job: RenderJob) -> None:
        """Validate model-specific request fields before any API call."""

    @abstractmethod
    def prepare(self, job: RenderJob, api_key: str) -> PreparedRequest:
        """Build a model-specific HTTP request."""

    @abstractmethod
    def decode(self, request: PreparedRequest, body: bytes) -> ProviderResult:
        """Decode a complete non-streaming HTTP response."""
