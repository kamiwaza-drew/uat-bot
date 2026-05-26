from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import Error, Page

# Well-known selectors for common Kamiwaza UI targets.
# Scenario YAML can reference these by name (e.g., target: "username")
# or provide CSS/XPath selectors directly.
WELL_KNOWN_SELECTORS: dict[str, list[str]] = {
    "username": [
        "input[name='username']",
        "input[type='email']",
        "input[name='email']",
        "input[placeholder*='user' i]",
        "#username",
    ],
    "password": [
        "input[name='password']",
        "input[type='password']",
        "#password",
    ],
    "submit": [
        "button[type='submit']",
        "button:has-text('Sign in')",
        "button:has-text('Log in')",
        "button:has-text('Login')",
        "input[type='submit']",
    ],
    "search": [
        "input[type='search']",
        "input[placeholder*='search' i]",
        "input[name='search']",
        "[data-testid='search-input']",
    ],
    "deploy_button": [
        "[data-testid='deploy-button']",
        "button:has-text('Deploy')",
        "button:has-text('deploy')",
    ],
    "first_model_card": [
        "[data-testid='model-card']:first-child",
        "[data-testid='model-card'] a:first-of-type",
        ".model-card:first-child",
        ".model-card a:first-of-type",
        "main a[href^='/models/']:not([href*='overview']):first-of-type",
        "a[href^='/models/']:not([href*='overview']):first-of-type",
        "a[href*='/models/']:not([href*='docs.kamiwaza.ai']):first-of-type",
    ],
    "first_app_card": [
        "[data-testid='app-card']:first-child",
        "[data-testid='app-card'] a:first-of-type",
        ".app-card:first-child",
        ".app-card a:first-of-type",
        "main a[href^='/apps/']:first-of-type",
        "a[href^='/apps/']:first-of-type",
        "a[href*='/apps/']:not([href*='docs.kamiwaza.ai']):first-of-type",
        "button:has-text('Deploy')",
    ],
    "sidebar_models": [
        "a[href='/models']",
        "[data-testid='nav-models']",
        "nav a:has-text('Models')",
    ],
    "sidebar_apps": [
        "a[href='/apps']",
        "[data-testid='nav-apps']",
        "nav a:has-text('Apps')",
        "nav a:has-text('App Garden')",
    ],
    "sidebar_cluster": [
        "a[href*='/cluster']",
        "[data-testid='nav-cluster']",
        "nav a:has-text('Cluster')",
    ],
    "sidebar_vectordbs": [
        "a[href*='/vectordb']",
        "[data-testid='nav-vectordb']",
        "nav a:has-text('Vector')",
    ],
    "sidebar_workrooms": [
        "a[href='/workrooms']",
        "a[href='/workroom']",
        "a[href*='/workrooms']",
        "a[href*='/workroom']",
        "[data-testid='nav-workrooms']",
        "[data-testid='nav-workroom']",
        "nav a:has-text('Workrooms')",
        "nav a:has-text('Workroom')",
        "button:has-text('Workrooms')",
    ],
    "sidebar_settings": [
        "a[href='/settings']",
        "[data-testid='nav-settings']",
        "nav a:has-text('Settings')",
    ],
    "confirm_button": [
        "button:has-text('Confirm')",
        "button:has-text('Yes')",
        "button:has-text('OK')",
        "[data-testid='confirm-button']",
    ],
    "cancel_button": [
        "button:has-text('Cancel')",
        "button:has-text('No')",
        "[data-testid='cancel-button']",
    ],
    "close_button": [
        "button:has-text('Close')",
        "button[aria-label='close']",
        "[data-testid='close-button']",
    ],
    "consent_accept": [
        "button:has-text('Accept')",
        "button:has-text('I Agree')",
        "button:has-text('Consent')",
        "[data-testid='consent-accept']",
    ],
    # Kaizen (OpenHands-based) UI selectors
    "kaizen_first_agent_card": [
        "h3",  # Agent card titles are h3 elements on the agents grid
    ],
    "kaizen_chat_button": [
        "button:has-text('Chat')",
        "a:has-text('Chat')",
    ],
    "kaizen_chat_input": [
        "textarea[placeholder*='What should we work on' i]",
        "textarea[placeholder*='Send a message' i]",
        "textarea[placeholder*='work on' i]",
        "textarea[placeholder*='message' i]",
        "textarea[data-testid='chat-input']",
        "textarea[placeholder*='Type' i]",
        "#chat-input",
        ".chat-input textarea",
        "[data-testid='msg-input']",
    ],
    "kaizen_send_button": [
        # Kaizen v3 message-input.tsx renders the send button with
        # aria-label="Send message" (or "Pause agent" when a reply is
        # in flight). Match that first.
        "button[aria-label='Send message']",
        "button[aria-label*='send message' i]",
        "button[aria-label*='send' i]:not([aria-label*='pause' i])",
        "button[data-testid='send-button']",
        "button:has-text('Send')",
        # NOTE: button[type='submit'] removed — it matched leftover form
        # buttons (e.g., the agent-create wizard's Continue/Create button
        # still in DOM) and caused clicks on the wrong element.
        ".send-button",
    ],
    "kaizen_new_conversation": [
        "button[data-testid='new-conversation']",
        "button:has-text('New Conversation')",
        "button:has-text('New Chat')",
        "a:has-text('New Conversation')",
        "a:has-text('New Chat')",
        "[data-testid='new-session']",
        "button:has-text('New Session')",
    ],
    "kaizen_conversation_list": [
        "[data-testid='conversation-list']",
        ".conversation-list",
        "nav[aria-label*='conversation' i]",
        "#conversation-panel",
    ],
    "kaizen_agent_response": [
        "[data-testid='agent-message']",
        ".message-agent",
        ".agent-response",
        "[data-role='assistant']",
        ".assistant-message",
    ],
}


async def resolve_selector(page: Page, target: str) -> str | None:
    """Resolve a target name to an actual CSS selector.

    If target is a well-known name (e.g., "username"), tries each candidate
    selector until one is visible on the page. Otherwise, treats target as
    a raw CSS selector and checks visibility directly.
    """
    candidates = WELL_KNOWN_SELECTORS.get(target)
    if candidates:
        return await _first_visible(page, candidates)
    # Treat as raw selector
    result = await _first_visible(page, [target])
    return result


async def _first_visible(page: Page, selectors: list[str]) -> str | None:
    """Return the first selector that matches a visible element."""
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = await locator.count()
        except Error:
            continue
        if count <= 0:
            continue
        try:
            if await locator.first.is_visible(timeout=2000):
                return selector
        except Error:
            continue
    return None


async def _dismiss_known_overlays(page: Page) -> None:
    """Best-effort dismissal of common onboarding overlays that intercept clicks."""
    try:
        if await page.locator("#react-joyride-portal").count() <= 0:
            return
    except Error:
        return

    close_selectors = [
        "#react-joyride-portal button:has-text('Skip')",
        "#react-joyride-portal button:has-text('Done')",
        "#react-joyride-portal button:has-text('Close')",
        "#react-joyride-portal button[aria-label='Close']",
        "#react-joyride-portal [data-action='close']",
    ]

    for selector in close_selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() <= 0:
                continue
            if not await locator.is_visible(timeout=500):
                continue
            await locator.click(timeout=1000)
            await asyncio.sleep(0.2)
        except Error:
            continue

    try:
        await page.keyboard.press("Escape")
    except Error:
        pass
    await asyncio.sleep(0.2)


async def navigate(page: Page, url: str, wait_for: str = "domcontentloaded") -> None:
    """Navigate to a URL and wait for the specified load state."""
    valid_states = {"domcontentloaded", "networkidle", "load", "commit"}
    state = wait_for if wait_for in valid_states else "domcontentloaded"
    await page.goto(url, wait_until=state, timeout=60_000)


async def click(page: Page, target: str, timeout: int = 10) -> None:
    """Click an element by resolving the target to a selector."""
    selector = await resolve_selector(page, target)
    if not selector:
        raise Error(f"Could not find clickable element for target: {target}")
    try:
        await page.click(selector, timeout=timeout * 1000)
    except Error as exc:
        text = str(exc)
        if "intercepts pointer events" not in text and "Timeout" not in text:
            raise
        await _dismiss_known_overlays(page)
        selector = await resolve_selector(page, target) or selector
        await page.click(selector, timeout=timeout * 1000)


async def hover(page: Page, target: str, timeout: int = 10) -> None:
    """Hover over an element by resolving the target to a selector."""
    selector = await resolve_selector(page, target)
    if not selector:
        raise Error(f"Could not find element for hover target: {target}")
    await page.hover(selector, timeout=timeout * 1000)
    await asyncio.sleep(0.3)  # let hover effects settle


async def fill(page: Page, target: str, value: str, timeout: int = 10) -> None:
    """Fill a text input by resolving the target to a selector."""
    selector = await resolve_selector(page, target)
    if not selector:
        raise Error(f"Could not find input element for target: {target}")
    await page.fill(selector, value, timeout=timeout * 1000)


async def scroll(page: Page, direction: str = "down", amount: int = 500) -> None:
    """Scroll the page in the given direction."""
    delta = amount if direction == "down" else -amount
    await page.mouse.wheel(0, delta)
    await asyncio.sleep(0.3)  # let scroll settle


async def wait_for_element(
    page: Page,
    target: str,
    timeout: int = 30,
    state: str = "visible",
) -> bool:
    """Wait for an element to reach a specific state."""
    selector = await resolve_selector(page, target)
    if not selector:
        # Wait and retry — element might appear later
        for _ in range(min(timeout, 10)):
            await asyncio.sleep(1)
            selector = await resolve_selector(page, target)
            if selector:
                break
        if not selector:
            return False

    try:
        await page.locator(selector).first.wait_for(
            state=state, timeout=timeout * 1000
        )
        return True
    except Error:
        return False


async def check_validation(
    page: Page,
    validations: list[dict[str, Any]],
) -> list[str]:
    """Run non-vision validations against the page. Returns list of failures."""
    failures: list[str] = []

    for v in validations:
        if "no_errors" in v and v["no_errors"]:
            # Check for common error indicators
            error_selectors = [
                ".MuiAlert-standardError",
                "[role='alert']",
                ".error-banner",
                ".toast-error",
            ]
            for sel in error_selectors:
                try:
                    count = await page.locator(sel).count()
                    if count > 0:
                        text = await page.locator(sel).first.text_content()
                        failures.append(f"Error element found ({sel}): {text}")
                except Error:
                    pass

        if "page_contains" in v:
            text = v["page_contains"]
            try:
                content = await page.content()
                if text.lower() not in content.lower():
                    failures.append(f"Page does not contain: {text}")
            except Error as exc:
                failures.append(f"Could not check page content: {exc}")

        if "element_visible" in v:
            sel = v["element_visible"]
            try:
                visible = await page.locator(sel).first.is_visible(timeout=3000)
                if not visible:
                    failures.append(f"Element not visible: {sel}")
            except Error:
                failures.append(f"Element not found: {sel}")

        if "url_contains" in v:
            current = page.url
            if v["url_contains"] not in current:
                failures.append(
                    f"URL does not contain '{v['url_contains']}': {current}"
                )

    return failures
