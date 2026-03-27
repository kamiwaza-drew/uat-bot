"""Interactive browser explorer that uses an LLM to navigate a real app and build scenarios."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

logger = logging.getLogger(__name__)

MAX_STEPS = 25
STEP_TIMEOUT = 30


@dataclass
class ExplorerStep:
    """A single action taken by the explorer."""
    action: str
    target: str | None = None
    value: str | None = None
    url: str | None = None
    screenshot_path: str | None = None
    result: str = ""
    page_url: str = ""


@dataclass
class ExplorationResult:
    """Result of an interactive exploration session."""
    steps: list[ExplorerStep] = field(default_factory=list)
    yaml_content: str = ""
    errors: list[str] = field(default_factory=list)
    success: bool = False


async def explore_and_build(
    target_url: str,
    task_description: str,
    username: str = "admin",
    password: str = "kamiwaza",
    backend: str = "claude",
    max_steps: int = MAX_STEPS,
    on_step: Any | None = None,
) -> ExplorationResult:
    """Launch a browser, let the LLM explore interactively, and build a scenario.

    Args:
        target_url: The app URL to test.
        task_description: What the user wants to test (e.g., "create a new user").
        username: Login username.
        password: Login password.
        backend: LLM CLI backend ("claude" or "codex").
        max_steps: Maximum exploration steps.
        on_step: Optional async callback(step_num, description) for progress.
    """
    result = ExplorationResult()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                ignore_https_errors=True,
            )
            page = await context.new_page()

            # Step 1: Navigate to the app
            if on_step:
                await on_step(0, "Navigating to app")
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2)

            # Step 2: Handle login if we see a login page
            if on_step:
                await on_step(1, "Checking for login page")
            logged_in = await _try_login(page, username, password)
            if logged_in:
                result.steps.append(ExplorerStep(
                    action="login", result="Logged in successfully",
                    page_url=page.url,
                ))

            # Step 3: Interactive exploration loop
            conversation: list[dict[str, str]] = []
            for step_num in range(max_steps):
                if on_step:
                    await on_step(step_num + 2, f"Exploring step {step_num + 1}")

                # Take screenshot
                screenshot_bytes = await page.screenshot()

                # Get simplified page info
                page_info = await _get_page_info(page)

                # Ask the LLM what to do next
                llm_response = await _ask_llm(
                    backend=backend,
                    screenshot=screenshot_bytes,
                    task=task_description,
                    page_info=page_info,
                    conversation=conversation,
                    step_num=step_num,
                    max_steps=max_steps,
                )

                if not llm_response:
                    result.errors.append(f"LLM returned empty response at step {step_num}")
                    break

                conversation.append({"role": "assistant", "content": llm_response})

                # Parse the LLM's action
                action = _parse_action(llm_response)
                if action is None:
                    result.errors.append(f"Could not parse action from LLM at step {step_num}")
                    break

                # Check if the LLM says we're done
                if action["type"] == "done":
                    if on_step:
                        await on_step(step_num + 2, "LLM reports task complete")
                    result.success = True
                    break

                # Execute the action
                step = await _execute_action(page, action)
                step.page_url = page.url
                result.steps.append(step)

                # Brief wait for page to settle
                await asyncio.sleep(1)

                conversation.append({
                    "role": "user",
                    "content": f"Action result: {step.result}. Current URL: {page.url}",
                })

            # Step 4: Generate scenario YAML from the exploration
            if on_step:
                await on_step(max_steps + 2, "Generating scenario YAML")

            final_screenshot = await page.screenshot()
            yaml_content = await _generate_yaml(
                backend=backend,
                task=task_description,
                steps=result.steps,
                screenshot=final_screenshot,
                target_url=target_url,
            )
            result.yaml_content = yaml_content

            await context.close()
        finally:
            await browser.close()

    return result


async def _try_login(page: Page, username: str, password: str) -> bool:
    """Attempt to log in if a login form is detected."""
    login_selectors = [
        "input[name='username']", "input[type='email']",
        "input[name='email']", "input[placeholder*='user' i]",
    ]
    password_selectors = [
        "input[name='password']", "input[type='password']",
    ]
    submit_selectors = [
        "button[type='submit']", "button:has-text('Sign in')",
        "button:has-text('Log in')", "button:has-text('Login')",
        "input[type='submit']",
    ]

    username_el = await _first_visible(page, login_selectors)
    password_el = await _first_visible(page, password_selectors)

    if not username_el or not password_el:
        return False

    await page.fill(username_el, username)
    await page.fill(password_el, password)

    submit_el = await _first_visible(page, submit_selectors)
    if submit_el:
        await page.click(submit_el)
    else:
        await page.keyboard.press("Enter")

    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    await asyncio.sleep(2)
    return True


async def _first_visible(page: Page, selectors: list[str]) -> str | None:
    """Return the first selector that matches a visible element."""
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if await locator.count() > 0 and await locator.first.is_visible(timeout=1500):
                return selector
        except Exception:
            continue
    return None


async def _get_page_info(page: Page) -> str:
    """Get a simplified view of the page for the LLM."""
    try:
        info = await page.evaluate("""() => {
            const result = { url: location.href, title: document.title, elements: [] };

            // Collect interactive elements
            const interactable = document.querySelectorAll(
                'a[href], button, input, textarea, select, [role="button"], [onclick], [tabindex]'
            );
            const seen = new Set();
            for (const el of Array.from(interactable).slice(0, 80)) {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                if (rect.top > window.innerHeight * 2) continue;

                const tag = el.tagName.toLowerCase();
                const type = el.type || '';
                const text = (el.textContent || '').trim().substring(0, 60);
                const placeholder = el.placeholder || '';
                const href = el.href || '';
                const name = el.name || '';
                const ariaLabel = el.getAttribute('aria-label') || '';
                const testId = el.getAttribute('data-testid') || '';

                // Build a unique key to deduplicate
                const key = `${tag}|${text}|${href}|${name}`;
                if (seen.has(key)) continue;
                seen.add(key);

                // Build the best selector for this element
                let selector = tag;
                if (testId) selector = `[data-testid="${testId}"]`;
                else if (el.id) selector = `#${el.id}`;
                else if (name) selector = `${tag}[name="${name}"]`;
                else if (ariaLabel) selector = `${tag}[aria-label="${ariaLabel}"]`;
                else if (type && tag === 'input') selector = `input[type="${type}"]`;
                else if (text && (tag === 'button' || tag === 'a'))
                    selector = `${tag}:has-text("${text.substring(0, 30)}")`;
                else if (href) selector = `a[href="${href.replace(location.origin, '')}"]`;

                result.elements.push({
                    tag, type, text: text.substring(0, 40), placeholder,
                    selector, visible: rect.top < window.innerHeight,
                    y: Math.round(rect.top),
                });
            }
            return result;
        }""")
        return json.dumps(info, indent=2)
    except Exception as exc:
        return json.dumps({"url": page.url, "error": str(exc)})


async def _ask_llm(
    backend: str,
    screenshot: bytes,
    task: str,
    page_info: str,
    conversation: list[dict[str, str]],
    step_num: int,
    max_steps: int,
) -> str:
    """Ask the LLM what to do next, providing page state."""
    history_text = ""
    if conversation:
        history_text = "\n\nPREVIOUS ACTIONS:\n"
        for msg in conversation[-10:]:
            history_text += f"- {msg['content'][:200]}\n"

    prompt = f"""You are interactively exploring a web application to figure out how to: {task}

CURRENT PAGE STATE:
{page_info}

Step {step_num + 1} of {max_steps}.{history_text}

Respond with EXACTLY ONE JSON object (no other text) describing your next action:

For clicking: {{"type": "click", "selector": "<css selector from the page info>", "reason": "why"}}
For filling a field: {{"type": "fill", "selector": "<css selector>", "value": "<text to type>", "reason": "why"}}
For navigating: {{"type": "navigate", "url": "<relative or absolute url>", "reason": "why"}}
For scrolling: {{"type": "scroll", "direction": "down", "reason": "why"}}
For pressing a key: {{"type": "press", "key": "Enter", "reason": "why"}}
When task is complete: {{"type": "done", "reason": "what was accomplished"}}

RULES:
- Use the EXACT selectors from the CURRENT PAGE STATE elements list
- If the page doesn't have what you need, navigate to find it
- Take small, deliberate steps — one action per response
- Say "done" when you've verified the task succeeded (or if it's clear it can't be done)
- ONLY output the JSON object, nothing else"""

    return await _call_llm_cli(backend, prompt)


def _parse_action(text: str) -> dict[str, Any] | None:
    """Parse a JSON action from the LLM response."""
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences
    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    # Find first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


async def _execute_action(page: Page, action: dict[str, Any]) -> ExplorerStep:
    """Execute a parsed LLM action on the page."""
    action_type = action.get("type", "")
    selector = action.get("selector", "")
    value = action.get("value", "")
    url = action.get("url", "")
    reason = action.get("reason", "")

    step = ExplorerStep(action=action_type, target=selector, value=value, url=url)

    try:
        if action_type == "click":
            await page.click(selector, timeout=STEP_TIMEOUT * 1000)
            await asyncio.sleep(1)
            step.result = f"Clicked {selector}. {reason}"

        elif action_type == "fill":
            await page.fill(selector, value, timeout=STEP_TIMEOUT * 1000)
            step.result = f"Filled {selector} with '{value}'. {reason}"

        elif action_type == "navigate":
            nav_url = url
            if nav_url.startswith("/"):
                # Make relative URLs absolute using current origin
                origin = await page.evaluate("() => location.origin")
                nav_url = origin + nav_url
            await page.goto(nav_url, wait_until="domcontentloaded", timeout=STEP_TIMEOUT * 1000)
            await asyncio.sleep(1)
            step.result = f"Navigated to {nav_url}. {reason}"

        elif action_type == "scroll":
            direction = action.get("direction", "down")
            delta = 400 if direction == "down" else -400
            await page.mouse.wheel(0, delta)
            await asyncio.sleep(0.5)
            step.result = f"Scrolled {direction}. {reason}"

        elif action_type == "press":
            key = action.get("key", "Enter")
            await page.keyboard.press(key)
            await asyncio.sleep(0.5)
            step.result = f"Pressed {key}. {reason}"

        else:
            step.result = f"Unknown action type: {action_type}"

    except Exception as exc:
        step.result = f"ERROR: {exc}"

    return step


async def _call_llm_cli(backend: str, prompt: str, timeout: int = 120) -> str:
    """Call an LLM CLI backend with a text prompt."""
    try:
        if backend == "claude":
            proc = await asyncio.to_thread(
                subprocess.run,
                [
                    "claude", "-p", prompt,
                    "--output-format", "text",
                    "--allowedTools", "",
                ],
                capture_output=True, text=True, timeout=timeout,
            )
        else:
            proc = await asyncio.to_thread(
                subprocess.run,
                ["codex", "exec", "--full-auto", prompt],
                capture_output=True, text=True, timeout=timeout,
            )
        if proc.returncode != 0:
            logger.warning("LLM CLI failed (rc=%d): %s", proc.returncode, proc.stderr[:300])
            return ""
        return proc.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning("LLM CLI timed out after %ds", timeout)
        return ""


async def _generate_yaml(
    backend: str,
    task: str,
    steps: list[ExplorerStep],
    screenshot: bytes,
    target_url: str,
) -> str:
    """Ask the LLM to generate a scenario YAML from the recorded exploration steps."""
    steps_log = "\n".join(
        f"  {i+1}. [{s.action}] target={s.target or 'N/A'} value={s.value or 'N/A'} "
        f"url={s.page_url} result={s.result}"
        for i, s in enumerate(steps)
    )

    prompt = f"""Based on this successful browser exploration, generate a repeatable UAT scenario YAML.

TASK: {task}
TARGET URL: {target_url}

EXPLORATION LOG (what actually worked):
{steps_log}

Generate a YAML scenario that replays these steps reliably. Output ONLY raw YAML, no fences or explanation.

SCENARIO FORMAT:
name: <snake_case>
description: <one line>
timeout: 300
required_role: viewer
tags: [<relevant tags>]

steps:
  - action: navigate|click|fill|press|scroll|wait_for|wait_for_url|js_eval|screenshot|sleep
    url: <for navigate>
    target: <CSS selector>
    value: <for fill/js_eval/wait_for_url>
    timeout: <seconds>
    screenshot_name: <name>
    validate:
      - no_errors: true
      - vision: "<describe expected state>"

RULES:
1. Use the EXACT selectors that worked during exploration
2. Add screenshot steps after key actions for debugging
3. Add vision validation at important checkpoints
4. Include appropriate waits/sleeps for page loads
5. Login is handled automatically — do NOT include login steps
6. Use {{{{username}}}}, {{{{password}}}}, {{{{test_message}}}} for dynamic values
7. Output ONLY the YAML"""

    result = await _call_llm_cli(backend, prompt, timeout=180)
    if not result:
        return "# ERROR: LLM failed to generate YAML"
    return _extract_yaml(result)


def _extract_yaml(text: str) -> str:
    """Extract YAML from LLM output, stripping markdown fences if present."""
    match = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    lines = text.strip().splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("name:"):
            return "\n".join(lines[i:]).strip()
    return text.strip()
