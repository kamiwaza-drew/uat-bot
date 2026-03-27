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
    "press",
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


def detect_backends() -> list[str]:
    """Return all available LLM CLI backends."""
    available = []
    if shutil.which("claude"):
        available.append("claude")
    if shutil.which("codex") and os.environ.get("OPENAI_API_KEY"):
        available.append("codex")
    return available


def detect_backend() -> str | None:
    """Return the best available LLM CLI backend, or None."""
    backends = detect_backends()
    return backends[0] if backends else None


def _build_system_prompt() -> str:
    """Build a system prompt with full schema reference for the LLM."""
    selector_names = sorted(WELL_KNOWN_SELECTORS.keys())

    # Load existing scenarios to include as examples
    existing = load_all_scenarios()
    scenario_names = sorted(existing.keys())

    # Include a couple of real examples so the LLM sees the actual style
    example_scenarios = []
    for name in ("login", "settings", "kaizen_chat"):
        scenario = existing.get(name)
        if scenario and scenario.source_path:
            try:
                with open(scenario.source_path, "r", encoding="utf-8") as f:
                    example_scenarios.append(f.read().strip())
            except OSError:
                pass

    examples_block = ""
    if example_scenarios:
        examples_block = "EXAMPLE SCENARIOS (study these carefully for style and patterns):\n\n"
        examples_block += "\n\n---\n\n".join(example_scenarios)

    return textwrap.dedent(f"""\
        You are a UAT scenario generator for the Kamiwaza platform. Output ONLY valid YAML.
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
            target: <well-known selector name OR CSS selector>
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

        WELL-KNOWN SELECTOR NAMES (use these as target values — the test runner resolves
        them to multiple CSS fallback selectors automatically):
        {', '.join(selector_names)}

        EXISTING SCENARIOS: {', '.join(scenario_names)}

        {examples_block}

        PLACEHOLDERS for fill values:
        - {{{{username}}}} and {{{{password}}}} are auto-resolved from test user context
        - {{{{test_message}}}} is resolved from the user-configured test message
        - Leave value empty for username/password targets to auto-resolve

        CRITICAL RULES:
        1. Output raw YAML only, no markdown fences, no explanation
        2. For target values, STRONGLY PREFER well-known selector names listed above.
           Only use raw CSS selectors if no well-known name fits AND you are confident
           the selector exists. NEVER invent data-testid attributes — the Kamiwaza UI
           does not use them consistently.
        3. When you need to interact with elements you cannot be sure exist, use
           js_eval with error handling (return 'ERROR: ...' on failure, 'OK: ...' on
           success), or use vision validation to describe what should be visible.
        4. Include screenshot steps at key points for debugging.
        5. Use vision validation (validate: - vision: "...") to verify page state
           instead of relying on fragile CSS selectors for assertions.
        6. The login flow is handled automatically before your scenario runs — do NOT
           include login steps unless your scenario specifically tests auth.
        7. Keep scenarios focused — test one flow, not multiple unrelated features.
        8. For complex UI interactions (hover menus, React state changes), prefer
           js_eval with explicit event dispatching over simple click actions.
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
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        if backend == "codex":
            result = subprocess.run(
                ["codex", "exec", "--full-auto", combined_prompt],
                capture_output=True,
                text=True,
                timeout=120,
            )
        else:
            result = subprocess.run(
                [
                    "claude", "-p", combined_prompt,
                    "--output-format", "text",
                    "--allowedTools", "",
                ],
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
