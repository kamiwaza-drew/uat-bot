from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Awaitable, Callable

from playwright.async_api import Error, Page

from uat_bot.browser import actions
from uat_bot.browser.screenshots import ScreenshotManager
from uat_bot.scenarios.loader import Scenario, ScenarioStep

MetricSink = Callable[[dict[str, Any]], Awaitable[None]]
EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class StepResult:
    """Result of executing a single scenario step."""

    step_index: int
    action: str
    status: str  # ok, error, validation_failure, skipped
    duration_ms: int = 0
    screenshot: str | None = None
    detail: str = ""
    validation_failures: list[str] = field(default_factory=list)
    vision_analysis: dict[str, Any] | None = None


class ScenarioRunner:
    """Executes a parsed Scenario against a Playwright page."""

    def __init__(
        self,
        page: Page,
        scenario: Scenario,
        *,
        screenshot_manager: ScreenshotManager,
        worker_id: str,
        run_id: str,
        user_context: dict[str, str],
        metric_sink: MetricSink,
        event_sink: EventSink,
        base_url: str,
        vision_client: Any | None = None,
        guidance_context: str = "",
        step_offset: int = 0,
    ) -> None:
        self.page = page
        self.scenario = scenario
        self.screenshot_manager = screenshot_manager
        self.worker_id = worker_id
        self.run_id = run_id
        self.user_context = user_context
        self.metric_sink = metric_sink
        self.event_sink = event_sink
        self.base_url = base_url.rstrip("/")
        self.vision_client = vision_client
        self.guidance_context = guidance_context
        self._step_counter = step_offset
        self._results: list[StepResult] = []

    @property
    def results(self) -> list[StepResult]:
        return list(self._results)

    @property
    def step_counter(self) -> int:
        return self._step_counter

    @property
    def metric_context(self) -> dict[str, str]:
        context = dict(self.user_context)
        if context.get("password"):
            context["password"] = "***redacted***"
        return context

    async def run(self, cancel_event: asyncio.Event | None = None) -> list[StepResult]:
        """Execute all steps in the scenario. Returns list of step results."""
        await self.event_sink(
            "scenario.started",
            {
                "worker_id": self.worker_id,
                "scenario": self.scenario.name,
                "step_count": len(self.scenario.steps),
            },
        )

        for i, step in enumerate(self.scenario.steps):
            if cancel_event and cancel_event.is_set():
                break

            result = await self._execute_step(i, step)
            self._results.append(result)

            # Emit metric
            await self.metric_sink(
                {
                    **self.metric_context,
                    "run_id": self.run_id,
                    "worker_id": self.worker_id,
                    "scenario": self.scenario.name,
                    "step": self._step_counter,
                    "action": step.action,
                    "target": step.target or step.url or "",
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "screenshot": result.screenshot or "",
                    "detail": result.detail,
                    "validation_failures": result.validation_failures,
                }
            )

            # Stop on error unless it's a validation-only failure
            if result.status == "error":
                await self.event_sink(
                    "scenario.step_error",
                    {
                        "worker_id": self.worker_id,
                        "scenario": self.scenario.name,
                        "step": i,
                        "error": result.detail,
                    },
                )
                break

        status = "completed"
        if any(r.status == "error" for r in self._results):
            status = "error"
        elif any(r.status == "validation_failure" for r in self._results):
            status = "validation_failure"

        await self.event_sink(
            "scenario.finished",
            {
                "worker_id": self.worker_id,
                "scenario": self.scenario.name,
                "status": status,
                "steps_run": len(self._results),
                "steps_total": len(self.scenario.steps),
            },
        )

        return self._results

    async def _execute_step(self, index: int, step: ScenarioStep) -> StepResult:
        """Execute a single scenario step."""
        self._step_counter += 1
        ts_start = perf_counter()

        try:
            detail = await self._dispatch_action(step)
        except Error as exc:
            duration_ms = int((perf_counter() - ts_start) * 1000)
            shot = await self._capture(step.action)
            return StepResult(
                step_index=index,
                action=step.action,
                status="error",
                duration_ms=duration_ms,
                screenshot=shot,
                detail=str(exc),
            )

        duration_ms = int((perf_counter() - ts_start) * 1000)

        # Take screenshots for explicit screenshot steps, named steps, and
        # key interaction actions (fill, click, navigate, hover, js_eval).
        # Skip auto-capture for wait_for, wait_for_url, sleep, scroll.
        shot = None
        _auto_capture_actions = {"screenshot", "fill", "click", "navigate", "hover", "js_eval"}
        if step.screenshot_name or step.action in _auto_capture_actions:
            shot_name = step.screenshot_name or step.action
            shot = await self._capture(shot_name)

        # Run validations
        validation_failures = []
        if step.validate:
            non_vision = [v for v in step.validate if "vision" not in v and "vision_check" not in v]
            if non_vision:
                validation_failures = await actions.check_validation(self.page, non_vision)

            # Vision validations
            vision_checks = [v for v in step.validate if "vision" in v or "vision_check" in v]
            if vision_checks and self.vision_client:
                for vc in vision_checks:
                    prompt = vc.get("vision") or vc.get("vision_check", "")
                    try:
                        screenshot_bytes = await self.page.screenshot()
                        from uat_bot.vision.schemas import PageValidation

                        analysis = await self.vision_client.analyze(
                            screenshot=screenshot_bytes,
                            prompt=prompt,
                            response_schema=PageValidation,
                        )
                        if not analysis.matches_expected:
                            validation_failures.append(
                                f"Vision check failed: {prompt} — "
                                f"{analysis.page_description}"
                            )
                    except NotImplementedError:
                        pass  # Vision not yet implemented
                    except Exception as exc:
                        validation_failures.append(f"Vision error: {exc}")

        status = "ok"
        if validation_failures:
            status = "validation_failure"

        return StepResult(
            step_index=index,
            action=step.action,
            status=status,
            duration_ms=duration_ms,
            screenshot=shot,
            detail=detail,
            validation_failures=validation_failures,
        )

    async def _dispatch_action(self, step: ScenarioStep) -> str:
        """Route step to the appropriate browser action. Returns detail string."""

        if step.action == "navigate":
            url = step.url or "/"
            if url.startswith("/"):
                url = self.base_url + url
            wait_for = step.wait_for or "domcontentloaded"
            await actions.navigate(self.page, url, wait_for=wait_for)
            return f"navigated to {url}"

        if step.action == "click":
            if not step.target:
                raise Error("click action requires a target")
            await actions.click(self.page, step.target, timeout=step.timeout)
            return f"clicked {step.target}"

        if step.action == "hover":
            if not step.target:
                raise Error("hover action requires a target")
            await actions.hover(self.page, step.target, timeout=step.timeout)
            return f"hovered {step.target}"

        if step.action == "fill":
            if not step.target:
                raise Error("fill action requires a target")
            value = self._resolve_value(step)
            await actions.fill(self.page, step.target, value, timeout=step.timeout)
            return f"filled {step.target}"

        if step.action == "scroll":
            await actions.scroll(self.page, direction=step.direction)
            return f"scrolled {step.direction}"

        if step.action == "wait_for":
            if step.target:
                found = await actions.wait_for_element(
                    self.page, step.target, timeout=step.timeout
                )
                if not found:
                    raise Error(f"Timed out waiting for element: {step.target}")
                return f"waited for {step.target}"

            if step.wait_for and step.wait_for in (
                "domcontentloaded",
                "networkidle",
                "load",
            ):
                await self.page.wait_for_load_state(
                    step.wait_for, timeout=step.timeout * 1000
                )
                return f"waited for {step.wait_for}"

            # Vision-based wait: poll until LLM says condition met
            if step.validate and self.vision_client:
                return await self._vision_poll(step)

            # Fallback: just wait
            await asyncio.sleep(step.timeout)
            return f"waited {step.timeout}s (no condition)"

        if step.action == "wait_for_url":
            pattern = step.value or step.url or ""
            if not pattern:
                raise Error("wait_for_url requires a value or url pattern")
            await self.page.wait_for_url(
                lambda url, p=pattern: p in url,
                timeout=step.timeout * 1000,
            )
            return f"URL matched pattern: {pattern}"

        if step.action == "js_eval":
            expression = self._resolve_value(step)
            if not expression:
                raise Error("js_eval action requires a value with the JS expression")
            result = await self.page.evaluate(expression)
            result_str = str(result)[:500]
            if result_str.startswith("ERROR:"):
                raise Error(f"js_eval error: {result_str}")
            return f"js_eval returned: {result_str}"

        if step.action == "screenshot":
            return "screenshot captured"

        if step.action == "vision_assert":
            # Handled in validation phase
            return "vision assertion (see validation)"

        if step.action == "press":
            key = step.value or step.target or ""
            if not key:
                raise Error("press action requires a value or target with the key name (e.g. Enter, ArrowDown)")
            await self.page.keyboard.press(key)
            return f"pressed key: {key}"

        if step.action == "sleep":
            duration = step.timeout
            await asyncio.sleep(duration)
            return f"slept {duration}s"

        raise Error(f"Unknown action: {step.action}")

    async def _vision_poll(self, step: ScenarioStep) -> str:
        """Poll with vision checks until condition is met or timeout."""
        deadline = perf_counter() + step.timeout
        interval = step.poll_interval

        while perf_counter() < deadline:
            screenshot_bytes = await self.page.screenshot()
            for v in step.validate:
                prompt = v.get("vision") or v.get("vision_check", "")
                if not prompt:
                    continue
                try:
                    from uat_bot.vision.schemas import PageValidation

                    analysis = await self.vision_client.analyze(
                        screenshot=screenshot_bytes,
                        prompt=prompt,
                        response_schema=PageValidation,
                    )
                    if analysis.matches_expected:
                        return f"vision condition met: {prompt}"
                except (NotImplementedError, Exception):
                    pass

            await asyncio.sleep(interval)

        return f"vision poll timed out after {step.timeout}s"

    def _resolve_value(self, step: ScenarioStep) -> str:
        """Resolve the fill value — supports {{username}} and {{password}} placeholders."""
        value = step.value or ""

        if value == "{{username}}" or (step.target == "username" and not value):
            return self.user_context.get("username", "")
        if value == "{{password}}" or (step.target == "password" and not value):
            return self.user_context.get("password", "")

        # Generic placeholder resolution
        for key, val in self.user_context.items():
            value = value.replace(f"{{{{{key}}}}}", val)

        return value

    async def _capture(self, action_name: str) -> str | None:
        """Take a screenshot and return its filename."""
        try:
            path = await self.screenshot_manager.capture(
                self.page,
                self.worker_id,
                self._step_counter,
                action_name,
                full_page=False,
            )
            # Emit screenshot event
            await self.event_sink(
                "worker.screenshot",
                {
                    "worker_id": self.worker_id,
                    "screenshot": path.relative_to(
                        self.screenshot_manager.run_dir
                    ).as_posix(),
                },
            )
            return path.name
        except Exception:
            return None
