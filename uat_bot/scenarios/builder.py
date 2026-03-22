from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from typing import Any

import yaml

from uat_bot.browser.actions import WELL_KNOWN_SELECTORS
from uat_bot.scenarios.loader import Scenario, ScenarioStep, load_all_scenarios

VALID_ACTIONS = [
    "navigate",
    "click",
    "hover",
    "fill",
    "scroll",
    "wait_for",
    "wait_for_url",
    "js_eval",
    "screenshot",
    "vision_assert",
    "sleep",
]

VALID_VALIDATIONS = [
    "no_errors",
    "page_contains",
    "element_visible",
    "url_contains",
    "vision",
    "vision_check",
]


def detect_backend() -> str | None:
    """Return the best available LLM CLI backend, or None."""
    if shutil.which("codex") and os.environ.get("OPENAI_API_KEY"):
        return "codex"
    if shutil.which("claude") and os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return None


def _build_system_prompt() -> str:
    """Build a system prompt with full schema reference for the LLM."""
    selector_names = sorted(WELL_KNOWN_SELECTORS.keys())

    existing = load_all_scenarios()
    scenario_names = sorted(existing.keys())

    return textwrap.dedent(f"""\
        You are a UAT scenario generator. Output ONLY valid YAML for a browser test scenario.
        Do NOT include any explanation, markdown fences, or commentary — just raw YAML.

        SCENARIO SCHEMA:
        ```
        name: <snake_case_name>
        description: <one line description>
        timeout: <int, seconds, default 300>
        required_role: viewer | editor | admin
        tags: [<tag>, ...]

        steps:
          - action: <one of: {', '.join(VALID_ACTIONS)}>
            url: <for navigate action, relative path like /settings>
            target: <CSS selector or well-known name>
            value: <for fill/js_eval/wait_for_url>
            wait_for: domcontentloaded | networkidle | load
            timeout: <int, seconds>
            screenshot_name: <optional name>
            direction: up | down  # for scroll
            validate:
              - no_errors: true
              - page_contains: "<text>"
              - element_visible: "<selector>"
              - url_contains: "<substring>"
              - vision: "<description of what page should look like>"
        ```

        WELL-KNOWN SELECTOR NAMES (use as target instead of raw CSS):
        {', '.join(selector_names)}

        EXISTING SCENARIOS FOR REFERENCE:
        {', '.join(scenario_names)}

        PLACEHOLDERS for fill values:
        - {{{{username}}}} and {{{{password}}}} are auto-resolved from test user context
        - Leave value empty for username/password targets to auto-resolve

        RULES:
        1. Output raw YAML only, no markdown fences, no explanation
        2. Every scenario must have name, description, and at least one step
        3. Every step must have an action field
        4. Use well-known selector names when possible
        5. Include screenshot steps at key verification points
        6. Include validate checks to verify expected outcomes
        7. Start with a navigate step to the relevant page
    """)


def _extract_yaml(text: str) -> str:
    """Extract YAML from LLM output, stripping markdown fences if present."""
    # Try to find ```yaml ... ``` block
    match = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try to find ``` ... ``` block
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Strip any leading non-YAML text before the first "name:" line
    lines = text.strip().splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("name:"):
            start = i
            break
    return "\n".join(lines[start:]).strip()


def _validate_parsed(parsed: dict[str, Any]) -> list[str]:
    """Validate a parsed YAML dict against the scenario schema. Returns errors."""
    errors: list[str] = []

    if not isinstance(parsed, dict):
        return ["YAML did not parse to a dict"]

    if "name" not in parsed:
        errors.append("Missing required field: name")
    if "steps" not in parsed or not isinstance(parsed.get("steps"), list):
        errors.append("Missing or invalid 'steps' (must be a list)")
        return errors

    for i, step in enumerate(parsed["steps"]):
        if not isinstance(step, dict):
            errors.append(f"Step {i}: not a dict")
            continue
        action = step.get("action")
        if not action:
            errors.append(f"Step {i}: missing 'action'")
        elif action not in VALID_ACTIONS:
            errors.append(f"Step {i}: unknown action '{action}' (valid: {', '.join(VALID_ACTIONS)})")

    return errors


def generate_scenario(
    prompt: str,
    name: str | None = None,
    tags: list[str] | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    """Generate a scenario YAML from a natural language prompt using an LLM CLI.

    Returns dict with keys: yaml_content, parsed, name, errors, backend_used.
    """
    if backend is None:
        backend = detect_backend()
    if backend is None:
        return {
            "yaml_content": "",
            "parsed": {},
            "name": "",
            "errors": ["No LLM backend available. Install codex (with OPENAI_API_KEY) or claude (with ANTHROPIC_API_KEY)."],
            "backend_used": "none",
        }

    system_prompt = _build_system_prompt()

    user_prompt = prompt
    if name:
        user_prompt += f"\n\nUse scenario name: {name}"
    if tags:
        user_prompt += f"\nInclude tags: {', '.join(tags)}"

    try:
        if backend == "codex":
            result = subprocess.run(
                ["codex", "--quiet", "--full-context", "-p", f"{system_prompt}\n\n{user_prompt}"],
                capture_output=True,
                text=True,
                timeout=120,
            )
        else:
            result = subprocess.run(
                ["claude", "-p", f"{system_prompt}\n\n{user_prompt}", "--output-format", "text"],
                capture_output=True,
                text=True,
                timeout=120,
            )

        if result.returncode != 0:
            stderr = result.stderr.strip()[:500]
            return {
                "yaml_content": "",
                "parsed": {},
                "name": "",
                "errors": [f"{backend} CLI failed (rc={result.returncode}): {stderr}"],
                "backend_used": backend,
            }

        raw_output = result.stdout.strip()
        if not raw_output:
            return {
                "yaml_content": "",
                "parsed": {},
                "name": "",
                "errors": [f"{backend} returned empty output"],
                "backend_used": backend,
            }

    except subprocess.TimeoutExpired:
        return {
            "yaml_content": "",
            "parsed": {},
            "name": "",
            "errors": [f"{backend} CLI timed out after 120s"],
            "backend_used": backend,
        }
    except FileNotFoundError:
        return {
            "yaml_content": "",
            "parsed": {},
            "name": "",
            "errors": [f"{backend} CLI not found in PATH"],
            "backend_used": backend,
        }

    yaml_content = _extract_yaml(raw_output)

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        return {
            "yaml_content": yaml_content,
            "parsed": {},
            "name": name or "",
            "errors": [f"YAML parse error: {exc}"],
            "backend_used": backend,
        }

    if not isinstance(parsed, dict):
        return {
            "yaml_content": yaml_content,
            "parsed": {},
            "name": name or "",
            "errors": ["YAML did not parse to a mapping"],
            "backend_used": backend,
        }

    errors = _validate_parsed(parsed)
    scenario_name = parsed.get("name", name or "")

    return {
        "yaml_content": yaml_content,
        "parsed": parsed,
        "name": scenario_name,
        "errors": errors,
        "backend_used": backend,
    }
