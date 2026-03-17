from __future__ import annotations

import base64
import json
import logging
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from uat_bot.vision.prompts import PROMPTS, compose_prompt
from uat_bot.vision.schemas import (
    BugReport,
    CrossBrowserDiff,
    ExploratoryAction,
    PageValidation,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Map schema classes to their JSON schema for structured output
_SCHEMA_INSTRUCTIONS: dict[type[BaseModel], str] = {
    PageValidation: (
        "Respond with ONLY a JSON object matching this schema:\n"
        '{"matches_expected": bool, "errors_detected": [str], "loading_visible": bool, '
        '"layout_issues": [str], "confidence": float (0-1), "page_description": str}'
    ),
    ExploratoryAction: (
        "Respond with ONLY a JSON object matching this schema:\n"
        '{"action_type": "click"|"navigate"|"fill"|"scroll"|"report_bug", '
        '"target": str, "value": str|null, "reasoning": str}'
    ),
    CrossBrowserDiff: (
        "Respond with ONLY a JSON object matching this schema:\n"
        '{"has_meaningful_differences": bool, "differences": [str], '
        '"severity": "none"|"cosmetic"|"functional"|"broken"}'
    ),
    BugReport: (
        "Respond with ONLY a JSON object matching this schema:\n"
        '{"title": str, "description": str, "severity": "critical"|"major"|"minor"|"cosmetic", '
        '"reproduction_steps": [str], "affected_browsers": [str], "screenshot_refs": [str]}'
    ),
}


class VisionClient:
    """Anthropic Claude vision client for screenshot analysis."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        model_complex: str = "claude-opus-4-6",
        max_tokens: int = 1024,
    ) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.model_complex = model_complex
        self.max_tokens = max_tokens

    async def analyze(
        self,
        screenshot: bytes,
        prompt: str,
        response_schema: type[T],
        previous_screenshots: list[bytes] | None = None,
        use_complex_model: bool = False,
        guidance_context: str = "",
        component: str | None = None,
    ) -> T:
        """Send screenshot(s) to Claude and get structured analysis.

        Args:
            screenshot: PNG/JPEG bytes of the current page.
            prompt: What to analyze (can be a prompt key or free-form text).
            response_schema: Pydantic model class to parse the response into.
            previous_screenshots: Optional prior screenshots for comparison.
            use_complex_model: Use the more capable model for ambiguous cases.
            guidance_context: UAT guidance text for component-aware analysis.
            component: Target component name for context.

        Returns:
            Parsed Pydantic model instance.
        """
        # Resolve prompt if it's a known key
        if prompt in PROMPTS:
            prompt = compose_prompt(
                prompt,
                guidance_context=guidance_context,
                component=component,
            )

        # Build content blocks
        content: list[dict[str, Any]] = []

        # Add previous screenshots for context (e.g., detecting stuck spinners)
        if previous_screenshots:
            for i, prev in enumerate(previous_screenshots[-3:]):  # max 3 prior
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _detect_media_type(prev),
                            "data": base64.standard_b64encode(prev).decode("ascii"),
                        },
                    }
                )
                content.append(
                    {
                        "type": "text",
                        "text": f"(Previous screenshot {i + 1})",
                    }
                )

        # Add current screenshot
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _detect_media_type(screenshot),
                    "data": base64.standard_b64encode(screenshot).decode("ascii"),
                },
            }
        )
        content.append({"type": "text", "text": "(Current screenshot)"})

        # Add structured output instruction
        schema_instruction = _SCHEMA_INSTRUCTIONS.get(response_schema, "")
        full_prompt = f"{prompt}\n\n{schema_instruction}" if schema_instruction else prompt
        content.append({"type": "text", "text": full_prompt})

        model = self.model_complex if use_complex_model else self.model

        response = await self.client.messages.create(
            model=model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": content}],
        )

        # Extract text response
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        # Parse JSON from response
        parsed = _extract_json(text)
        return response_schema.model_validate(parsed)

    async def validate_page(
        self,
        screenshot: bytes,
        expected: str,
        **kwargs: Any,
    ) -> PageValidation:
        """Shortcut for page validation."""
        prompt = compose_prompt(
            "page_validation",
            expected=expected,
            **{k: v for k, v in kwargs.items() if k in ("guidance_context", "component")},
        )
        return await self.analyze(
            screenshot=screenshot,
            prompt=prompt,
            response_schema=PageValidation,
            **kwargs,
        )

    async def detect_errors(
        self,
        screenshot: bytes,
        **kwargs: Any,
    ) -> PageValidation:
        """Shortcut for error detection."""
        return await self.analyze(
            screenshot=screenshot,
            prompt="error_detection",
            response_schema=PageValidation,
            **kwargs,
        )

    async def suggest_next_action(
        self,
        screenshot: bytes,
        history: list[str],
        role: str = "viewer",
        **kwargs: Any,
    ) -> ExploratoryAction:
        """Shortcut for exploratory mode — suggest what to do next."""
        prompt = compose_prompt(
            "exploratory_next_action",
            history=", ".join(history[-10:]),
            role=role,
            **{k: v for k, v in kwargs.items() if k in ("guidance_context", "component")},
        )
        return await self.analyze(
            screenshot=screenshot,
            prompt=prompt,
            response_schema=ExploratoryAction,
            use_complex_model=True,
            **kwargs,
        )

    async def compare_browsers(
        self,
        screenshot_a: bytes,
        screenshot_b: bytes,
        browser_a: str,
        os_a: str,
        browser_b: str,
        os_b: str,
    ) -> CrossBrowserDiff:
        """Compare two screenshots from different browsers."""
        prompt = compose_prompt(
            "cross_browser_diff",
            browser_a=browser_a,
            os_a=os_a,
            browser_b=browser_b,
            os_b=os_b,
        )
        # Send both as "previous" + "current"
        return await self.analyze(
            screenshot=screenshot_b,
            prompt=prompt,
            response_schema=CrossBrowserDiff,
            previous_screenshots=[screenshot_a],
        )


def _detect_media_type(data: bytes) -> str:
    """Detect image media type from magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:3] == b"GIF":
        return "image/gif"
    return "image/png"  # default


def _extract_json(text: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences
    if "```" in text:
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                if in_block:
                    break
                in_block = True
                continue
            if in_block:
                json_lines.append(line)
        if json_lines:
            try:
                return json.loads("\n".join(json_lines))
            except json.JSONDecodeError:
                pass

    # Find first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM response as JSON: %s", text[:200])
    # Return a minimal valid response
    return {
        "matches_expected": False,
        "errors_detected": [f"Failed to parse vision response: {text[:200]}"],
        "loading_visible": False,
        "layout_issues": [],
        "confidence": 0.0,
        "page_description": "Parse error",
    }
