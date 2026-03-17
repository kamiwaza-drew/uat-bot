from __future__ import annotations

PROMPTS = {
    "page_validation": (
        "Look at this screenshot of the Kamiwaza platform.\n"
        "Expected state: {expected}\n\n"
        "Evaluate:\n"
        "1. Does the page match the expected state?\n"
        "2. Are there any error banners, toasts, or modal error dialogs?\n"
        "3. Is there a loading spinner or skeleton UI still visible?\n"
        "4. Are all text elements readable (not truncated, overlapping, or clipped)?\n"
        "5. Rate your confidence 0.0 to 1.0 that the page is in the expected state."
    ),
    "error_detection": (
        "Examine this screenshot for any signs of problems:\n"
        "- Error messages, red banners, or toast notifications\n"
        "- Broken layouts, overlapping elements, or misaligned components\n"
        "- Missing images or icons (broken image placeholders)\n"
        "- Spinners that appear stuck (compare with previous screenshot if available)\n"
        "- Empty states that should have content\n"
        "- Garbled text, placeholder text (lorem ipsum), or untranslated i18n keys\n"
        "- Console error indicators or debug output visible in the UI\n"
        "- HTTP error codes displayed (404, 500, etc.)\n"
        "- Modal dialogs blocking interaction unexpectedly"
    ),
    "cross_browser_diff": (
        "Compare these two screenshots of the same page rendered in different browsers:\n"
        "Screenshot 1: {browser_a} on {os_a}\n"
        "Screenshot 2: {browser_b} on {os_b}\n\n"
        "Identify any meaningful rendering differences. Ignore:\n"
        "- Minor anti-aliasing or font rendering differences\n"
        "- Slight scrollbar style differences\n\n"
        "Focus on:\n"
        "- Layout shifts or misalignment\n"
        "- Missing or differently-sized elements\n"
        "- Broken interactions (buttons, inputs not showing)\n"
        "- Color or contrast issues\n"
        "- Content that's visible in one but cut off in another"
    ),
    "exploratory_next_action": (
        "You are an expert QA tester stress-testing the Kamiwaza AI platform.\n"
        "You are logged in as role: {role}.\n"
        "Pages visited so far: {history}\n\n"
        "Looking at the current screenshot, choose ONE action to find bugs:\n"
        "- click(target_description) — click a button, link, or interactive element\n"
        "- navigate(url) — go to a specific URL path\n"
        "- fill(target_description, text) — type into an input field\n"
        "- scroll(down/up) — scroll the page\n"
        "- report_bug(description) — report a visual bug you've spotted\n\n"
        "Prefer:\n"
        "- Pages and features you haven't explored yet\n"
        "- Edge cases (empty inputs, very long text, special characters)\n"
        "- Interactive elements that might reveal errors\n"
        "- Admin-only features if you have admin role\n"
        "- Areas where the UI looks unusual or suspicious"
    ),
    "accessibility_check": (
        "Evaluate this screenshot for accessibility issues:\n"
        "- Is there sufficient color contrast between text and background?\n"
        "- Are interactive elements clearly distinguishable from non-interactive?\n"
        "- Is text readable at the current viewport size?\n"
        "- Do form fields appear to have visible labels?\n"
        "- Are focus indicators likely to be visible?\n"
        "- Is there any text that's too small to read comfortably?"
    ),
    "state_change": (
        "Compare these screenshots (previous and current) of the Kamiwaza platform.\n"
        "What changed between them?\n"
        "- Did a deployment status change?\n"
        "- Did new data appear or disappear?\n"
        "- Did a loading state resolve?\n"
        "- Is there an error that wasn't there before?\n"
        "- Did the page navigate to a different view?"
    ),
}


def compose_prompt(
    key: str,
    *,
    guidance_context: str = "",
    component: str | None = None,
    **kwargs: str,
) -> str:
    """Build a full prompt from a template key and optional guidance context."""
    template = PROMPTS.get(key, key)  # fall back to key as literal prompt

    # Substitute template variables
    try:
        base = template.format(**kwargs) if kwargs else template
    except KeyError:
        # Missing placeholders — use template as-is
        base = template

    if not guidance_context:
        return base

    component_line = f"Target component: {component}\n" if component else ""
    return (
        f"{base}\n\n"
        "--- Component-specific UAT guidance ---\n"
        f"{component_line}"
        f"{guidance_context}\n"
        "--- End guidance ---\n\n"
        "Use this guidance to inform your analysis and focus on component-specific concerns."
    )
