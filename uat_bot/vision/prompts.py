from __future__ import annotations

PROMPTS = {
    "page_validation": "Look at this screenshot and validate expected state: {expected}",
    "error_detection": "Identify visible UI issues, broken states, or error banners.",
    "cross_browser_diff": "Compare screenshots and identify meaningful rendering differences.",
    "exploratory_next_action": "Given page history {history}, choose the next bug-finding action.",
    "accessibility_check": "Evaluate accessibility issues visible in this screenshot.",
}


def compose_prompt(
    key: str,
    *,
    guidance_context: str = "",
    component: str | None = None,
    **kwargs,
) -> str:
    template = PROMPTS.get(key, "")
    base = template.format(**kwargs) if kwargs else template
    if not guidance_context:
        return base

    component_line = f"Target component: {component}\n" if component else ""
    return (
        f"{base}\n\n"
        "Component-specific UAT guidance:\n"
        f"{component_line}"
        f"{guidance_context}\n\n"
        "Follow this guidance when choosing/validating actions."
    )
