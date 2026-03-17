from __future__ import annotations

from pydantic import BaseModel


class VisionClient:
    """Phase-3 stub for Anthropic vision integration."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self.api_key = api_key
        self.model = model

    async def analyze(
        self,
        screenshot: bytes,
        prompt: str,
        response_schema: type[BaseModel],
        previous_screenshots: list[bytes] | None = None,
    ) -> BaseModel:
        raise NotImplementedError("Vision integration is planned for Phase 3")
